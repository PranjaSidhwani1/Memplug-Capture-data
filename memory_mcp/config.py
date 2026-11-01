"""Process configuration. Identity and grants come from here, never from a tool call."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from memory_mcp.domains import DOMAINS, resolve_domain

_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_local_env() -> None:
    _load_env_file(_ROOT / ".env")


load_local_env()


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    transport: str
    user_id: str
    database_url: str
    granted_domains: frozenset[str]


def _granted_domains() -> frozenset[str]:
    raw = os.environ.get("MEMPLUG_GRANTED_DOMAINS", "").strip()
    if not raw:
        return frozenset(domain.name for domain in DOMAINS)

    granted: set[str] = set()
    for part in raw.split(","):
        resolved = resolve_domain(part)
        if resolved is not None:
            granted.add(resolved)
    if not granted:
        known = ", ".join(domain.name for domain in DOMAINS)
        raise SystemExit(f"MEMPLUG_GRANTED_DOMAINS matched no known domains. Known domains: {known}")
    return frozenset(granted)


def database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip() or os.environ.get("POSTGRES_URL", "").strip()
    if not raw:
        return ""
    if "sslmode=" not in raw:
        raw += "&sslmode=require" if "?" in raw else "?sslmode=require"
    return raw


def public_base_url() -> str:
    configured = os.environ.get("MEMPLUG_PUBLIC_API_URL", "").strip().rstrip("/")
    if configured:
        return configured
    external = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    return external or "http://127.0.0.1:8000"


def load_settings() -> Settings:
    port_raw = os.environ.get("MEMPLUG_PORT", "8000")
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise SystemExit(f"MEMPLUG_PORT must be an integer, got {port_raw!r}") from exc

    transport = os.environ.get("MEMPLUG_TRANSPORT", "stdio").strip() or "stdio"
    if transport not in {"streamable-http", "stdio"}:
        raise SystemExit("MEMPLUG_TRANSPORT must be 'streamable-http' or 'stdio'")

    user_id = os.environ.get("MEMPLUG_USER_ID", "").strip()
    if transport == "stdio" and not user_id:
        raise SystemExit("MEMPLUG_USER_ID is not set. Use the Mongo user id that owns the memories.")

    url = database_url()
    if not url:
        raise SystemExit("DATABASE_URL is not set")

    return Settings(
        host=os.environ.get("MEMPLUG_HOST", "0.0.0.0"),
        port=port,
        transport=transport,
        user_id=user_id,
        database_url=url,
        granted_domains=_granted_domains(),
    )
