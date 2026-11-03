from __future__ import annotations

import hmac
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.bundles import SYSTEMS, TOOLS, build_bundle, destination, filename
from app.log import configure as configure_logging

configure_logging()
from app.config import (
    api_key,
    auth_secret,
    checkpoint_idle_minutes,
    checkpoint_tokens,
    meta_api_key,
    meta_model,
    mail_configured,
    postgres_url,
    public_api_url,
)
from app.security import issue_token, read_token
from app.store import ensure_store_indexes, save_message, stats
from app.users import (
    authenticate,
    create_api_key,
    create_team,
    create_user,
    ensure_indexes,
    get_user,
    get_user_by_email,
    join_team,
    leave_team,
    list_api_keys,
    list_teams,
    reveal_api_key,
    revoke_api_key,
    set_password,
    workspace_for_api_key,
)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UI_DIST = Path(__file__).resolve().parents[1] / "ui" / "dist"


log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    if _ON_RENDER:
        auth_secret()
    ensure_indexes()
    ensure_store_indexes()
    log.info("CHECKPOINT_TOKENS=%s CHECKPOINT_IDLE_MINUTES=%s", checkpoint_tokens(), checkpoint_idle_minutes())
    from app.checkpoint import start_idle_sweep

    start_idle_sweep()
    if postgres_url() and meta_api_key() and meta_model():
        try:
            from app.memories import ensure_schema

            ensure_schema()
            log.info("memory tables ready")
        except Exception:
            log.exception("memory tables were not created")
    else:
        log.info("memory extraction is waiting for META_API_KEY, META_MODEL, and DATABASE_URL")
    if postgres_url():
        try:
            from memory_mcp.server import warmup

            warmup()
        except Exception:
            log.exception("mcp memory store was not opened")
    async with _mcp_http.router.lifespan_context(_mcp_http):
        log.info("mcp endpoint /mcp")
        yield


_ON_RENDER = os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}
app = FastAPI(
    title="Memplug Capture API",
    lifespan=_lifespan,
    docs_url=None if _ON_RENDER else "/docs",
    redoc_url=None if _ON_RENDER else "/redoc",
    openapi_url=None if _ON_RENDER else "/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

from memory_mcp.server import http_app as mcp_http_app

_mcp_http = mcp_http_app()


class _McpEndpoint:
    """Serve the MCP app at /mcp. A function route would not receive the raw ASGI call."""

    async def __call__(self, scope, receive, send):
        scope = dict(scope)
        scope["path"] = "/"
        scope["raw_path"] = b"/"
        await _mcp_http(scope, receive, send)


app.add_route("/mcp", _McpEndpoint())
app.add_route("/mcp/", _McpEndpoint())


class MessageIn(BaseModel):
    source: str
    session_id: str
    project: str = ""
    role: Literal["user", "assistant"]
    content: str
    timestamp: str | None = None


class AccountIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class CodeIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class EmailIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)
    password: str = Field(min_length=8, max_length=200)


class KeyIn(BaseModel):
    name: str = Field(default="default", max_length=40)
    team_id: str | None = None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class JoinIn(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: str


class SessionOut(BaseModel):
    token: str
    user: UserOut


class MeOut(BaseModel):
    user: UserOut


def _send_code(email: str, purpose: str) -> None:
    from app.codes import clear_code, issue_code
    from app.mail import MailError, send_reset_code, send_signin_code

    try:
        code = issue_code(email, purpose)
    except ValueError:
        return
    try:
        if purpose == "reset":
            send_reset_code(email, code)
        else:
            send_signin_code(email, code)
    except MailError as exc:
        clear_code(email, purpose)
        detail = "The reset code could not be sent" if purpose == "reset" else "The sign-in code could not be sent"
        raise HTTPException(status_code=503, detail=detail) from exc


def _accept_code(email: str, purpose: str, code: str) -> None:
    from app.codes import check_code

    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != 6:
        raise HTTPException(status_code=400, detail="Enter the 6-digit code")
    try:
        check_code(email, purpose, digits)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _email(value: str) -> str:
    cleaned = value.strip().lower()
    if not _EMAIL.fullmatch(cleaned):
        raise HTTPException(status_code=400, detail="Enter a valid email")
    return cleaned


def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return token


def require_api_key(authorization: str | None = Header(default=None)) -> dict:
    token = _bearer(authorization)
    expected = api_key()
    if expected and len(token) == len(expected) and hmac.compare_digest(token, expected):
        return {"user_id": None}
    space = workspace_for_api_key(token)
    if not space:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return space


def require_user(authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = read_token(_bearer(authorization))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Sign in again") from exc
    user = get_user(str(payload["sub"]))
    if not user:
        raise HTTPException(status_code=401, detail="Sign in again")
    return user


def _api_base(request: Request) -> str:
    return public_api_url(str(request.base_url))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/auth/signup", response_model=SessionOut)
def signup(body: AccountIn) -> dict:
    name = body.name.strip()
    try:
        user = create_user(_email(body.email), body.password, name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"token": issue_token(user["id"], user["email"]), "user": user}


@app.post("/v1/auth/login")
def login(body: LoginIn) -> dict:
    user = authenticate(_email(body.email), body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Email or password is wrong")
    if not mail_configured():
        return {"token": issue_token(user["id"], user["email"]), "user": user}
    _send_code(user["email"], "signin")
    return {"otp_required": True, "email": user["email"]}


@app.post("/v1/auth/otp", response_model=SessionOut)
def verify_otp(body: CodeIn) -> dict:
    email = _email(body.email)
    _accept_code(email, "signin", body.code)
    user = get_user_by_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in again")
    return {"token": issue_token(user["id"], user["email"]), "user": user}


@app.post("/v1/auth/forgot")
def forgot_password(body: EmailIn) -> dict:
    if not mail_configured():
        raise HTTPException(status_code=503, detail="Password reset email is not configured")
    email = _email(body.email)
    if get_user_by_email(email):
        _send_code(email, "reset")
    return {"sent": True}


@app.post("/v1/auth/reset", response_model=SessionOut)
def reset_password(body: ResetIn) -> dict:
    email = _email(body.email)
    _accept_code(email, "reset", body.code)
    user = set_password(email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Sign in again")
    return {"token": issue_token(user["id"], user["email"]), "user": user}


@app.get("/v1/auth/me", response_model=MeOut)
def me(user: dict = Depends(require_user)) -> dict:
    return {"user": user}


@app.get("/v1/keys")
def keys(user: dict = Depends(require_user)) -> dict:
    return {"keys": list_api_keys(user["id"])}


@app.post("/v1/keys")
def make_key(body: KeyIn, user: dict = Depends(require_user)) -> dict:
    name = body.name.strip() or "default"
    team_id = body.team_id.strip() if isinstance(body.team_id, str) else ""
    try:
        created = create_api_key(user["id"], name, team_id or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return created


@app.get("/v1/teams")
def teams(user: dict = Depends(require_user)) -> dict:
    return {"teams": list_teams(user["id"])}


@app.post("/v1/teams")
def make_team(body: TeamIn, user: dict = Depends(require_user)) -> dict:
    try:
        return create_team(user["id"], body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/teams/join")
def join(body: JoinIn, user: dict = Depends(require_user)) -> dict:
    try:
        return join_team(user["id"], body.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v1/teams/{team_id}/members/me")
def leave(team_id: str, user: dict = Depends(require_user)) -> dict:
    try:
        left = leave_team(user["id"], team_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not left:
        raise HTTPException(status_code=404, detail="You are not on that team")
    return {"left": True}


@app.delete("/v1/keys/{key_id}")
def delete_key(key_id: str, user: dict = Depends(require_user)) -> dict:
    if not revoke_api_key(user["id"], key_id):
        raise HTTPException(status_code=404, detail="Key not found")
    return {"revoked": True}


@app.get("/v1/config/meta")
def config_meta(request: Request, _: dict = Depends(require_user)) -> dict:
    return {
        "api_url": _api_base(request),
        "tools": list(TOOLS),
        "systems": list(SYSTEMS),
        "destinations": {f"{tool}:{system}": destination(tool, system) for tool in TOOLS for system in SYSTEMS},
    }


@app.get("/v1/config/bundle")
def config_bundle(
    request: Request,
    tool: str = Query(...),
    os_name: str = Query(..., alias="os"),
    key_id: str = Query(...),
    user: dict = Depends(require_user),
) -> Response:
    if tool not in TOOLS or os_name not in SYSTEMS:
        raise HTTPException(status_code=400, detail="Choose Cursor, Claude, or Codex, and macOS or Windows")
    record = reveal_api_key(user["id"], key_id)
    if not record:
        raise HTTPException(status_code=404, detail="Choose an active API key")
    try:
        payload = build_bundle(tool, os_name, _api_base(request), record["key"])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    name = filename(tool, os_name)
    body = json.dumps(payload, indent=2) + "\n"
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/v1/capture/message")
def capture_message(body: MessageIn, auth: dict = Depends(require_api_key)) -> dict:
    saved = save_message(
        source=body.source,
        session_id=body.session_id,
        project=body.project,
        role=body.role,
        content=body.content,
        timestamp=body.timestamp,
        user_id=auth.get("user_id"),
        workspace_type=auth.get("workspace_type") or "user",
        workspace_id=auth.get("workspace_id") or auth.get("user_id") or "",
    )
    return {"saved": saved}


@app.get("/v1/capture/stats")
def capture_stats(auth: dict = Depends(require_api_key)) -> dict[str, int]:
    return stats(auth.get("user_id"))


if _UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_UI_DIST, html=True), name="ui")
