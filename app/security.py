from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from cryptography.fernet import Fernet, InvalidToken

from app.config import auth_secret

_TOKEN_TTL = 14 * 24 * 60 * 60
_PBKDF2_ROUNDS = 210_000


def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    material = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), material, _PBKDF2_ROUNDS)
    return material.hex(), digest.hex()


def password_matches(password: str, salt_hex: str, digest_hex: str) -> bool:
    _, candidate = hash_password(password, bytes.fromhex(salt_hex))
    return hmac.compare_digest(candidate, digest_hex)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_api_key() -> str:
    return "mpl_" + secrets.token_urlsafe(32)


def _fernet() -> Fernet:
    digest = hashlib.sha256(auth_secret().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def seal_api_key(raw: str) -> str:
    return _fernet().encrypt(raw.encode("utf-8")).decode("ascii")


def open_api_key(sealed: str) -> str:
    try:
        return _fernet().decrypt(sealed.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored API key cannot be opened") from exc


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def issue_token(user_id: str, email: str) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    body = _b64(
        json.dumps(
            {"sub": user_id, "email": email, "iat": now, "exp": now + _TOKEN_TTL},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signing = f"{header}.{body}"
    signature = hmac.new(auth_secret().encode("utf-8"), signing.encode("ascii"), hashlib.sha256).digest()
    return f"{signing}.{_b64(signature)}"


def read_token(token: str) -> dict:
    try:
        header_b64, body_b64, signature = token.split(".", 2)
        signing = f"{header_b64}.{body_b64}".encode("ascii")
        expected = hmac.new(auth_secret().encode("utf-8"), signing, hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), signature):
            raise ValueError("bad signature")
        header = json.loads(_unb64(header_b64))
        payload = json.loads(_unb64(body_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("invalid session") from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise ValueError("invalid session")
    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < int(time.time()):
        raise ValueError("session expired")
    if not payload.get("sub"):
        raise ValueError("invalid session")
    return payload
