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
    postgres_url,
    public_api_url,
)
from app.security import issue_token, read_token
from app.store import ensure_store_indexes, save_message, stats
from app.users import (
    authenticate,
    create_api_key,
    create_user,
    ensure_indexes,
    get_user,
    list_api_keys,
    reveal_api_key,
    revoke_api_key,
    user_id_for_api_key,
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


class KeyIn(BaseModel):
    name: str = Field(default="default", max_length=40)


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
    user_id = user_id_for_api_key(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return {"user_id": user_id}


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


@app.post("/v1/auth/login", response_model=SessionOut)
def login(body: LoginIn) -> dict:
    user = authenticate(_email(body.email), body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Email or password is wrong")
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
    try:
        created = create_api_key(user["id"], name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return created


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
    )
    return {"saved": saved}


@app.get("/v1/capture/stats")
def capture_stats(auth: dict = Depends(require_api_key)) -> dict[str, int]:
    return stats(auth.get("user_id"))


if _UI_DIST.is_dir():
    app.mount("/", StaticFiles(directory=_UI_DIST, html=True), name="ui")
