import os
from pathlib import Path


def load_local_env() -> None:
    """Fill in variables that are not already set. Existing environment wins."""
    roots = [
        Path(__file__).resolve().parents[1] / ".env",
    ]
    seen: set[Path] = set()
    for path in roots:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_local_env()


def mongo_uri() -> str:
    uri = os.environ.get("MONGODB_URI", "").strip()
    if not uri:
        raise RuntimeError("MONGODB_URI is not set")
    return uri


def mongo_db() -> str:
    return os.environ.get("MONGODB_DB", "memplug").strip() or "memplug"


def api_key() -> str:
    return os.environ.get("MEMPLUG_CAPTURE_API_KEY", "").strip()


def auth_secret() -> str:
    configured = os.environ.get("MEMPLUG_AUTH_SECRET", "").strip()
    if configured:
        return configured
    path = Path(__file__).resolve().parents[1] / ".auth_secret"
    if path.is_file():
        saved = path.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    if os.environ.get("RENDER", "").strip().lower() in {"1", "true", "yes"}:
        raise RuntimeError("MEMPLUG_AUTH_SECRET is not set")
    import secrets

    generated = secrets.token_urlsafe(32)
    path.write_text(generated + "\n", encoding="utf-8")
    return generated


def meta_api_key() -> str:
    return os.environ.get("META_API_KEY", "").strip()


def meta_model() -> str:
    return os.environ.get("META_MODEL", "").strip()


def checkpoint_tokens() -> int:
    raw = os.environ.get("CHECKPOINT_TOKENS", "1000").strip()
    try:
        value = int(raw)
    except ValueError:
        return 1000
    return value if value > 0 else 1000


def checkpoint_idle_minutes() -> int:
    raw = os.environ.get("CHECKPOINT_IDLE_MINUTES", "30").strip()
    try:
        value = int(raw)
    except ValueError:
        return 30
    return value if value > 0 else 30


def postgres_url() -> str:
    """Neon connection string. DATABASE_URL is the name Neon shows."""
    raw = os.environ.get("DATABASE_URL", "").strip() or os.environ.get("POSTGRES_URL", "").strip()
    if not raw:
        return ""
    if "sslmode=" not in raw:
        raw += "&sslmode=require" if "?" in raw else "?sslmode=require"
    return raw


def public_api_url(fallback: str) -> str:
    configured = os.environ.get("MEMPLUG_PUBLIC_API_URL", "").strip().rstrip("/")
    if configured:
        return configured
    # Behind Render's proxy, request.base_url is the internal host, not the public one.
    external = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    return external or fallback.rstrip("/")
