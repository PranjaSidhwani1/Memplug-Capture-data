"""One-time codes for sign-in and password reset. Only a hash is stored."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from app.config import auth_secret
from app.store import database

_TTL = timedelta(minutes=10)
_COOLDOWN = timedelta(seconds=60)
_MAX_ATTEMPTS = 5


def issue_code(email: str, purpose: str) -> str:
    """Create a 6-digit code. A still-fresh code is not replaced."""
    now = datetime.now(timezone.utc)
    col = _codes()
    existing = col.find_one({"email": email, "purpose": purpose})
    if existing and _still_fresh(existing, now):
        raise ValueError("Wait a minute before asking for another code")
    code = f"{secrets.randbelow(1_000_000):06d}"
    col.update_one(
        {"email": email, "purpose": purpose},
        {
            "$set": {
                "email": email,
                "purpose": purpose,
                "code_hash": _digest(email, purpose, code),
                "created_at": now,
                "expires_at": now + _TTL,
                "attempts": 0,
            }
        },
        upsert=True,
    )
    return code


def check_code(email: str, purpose: str, code: str) -> None:
    """Accept the code once. A wrong or expired code raises ValueError."""
    now = datetime.now(timezone.utc)
    col = _codes()
    row = col.find_one({"email": email, "purpose": purpose})
    expires = row.get("expires_at") if row else None
    if row is None or not isinstance(expires, datetime) or expires <= now:
        raise ValueError("That code is expired. Ask for a new one")
    if int(row.get("attempts") or 0) >= _MAX_ATTEMPTS:
        col.delete_one({"_id": row["_id"]})
        raise ValueError("That code is expired. Ask for a new one")
    if not hmac.compare_digest(_digest(email, purpose, code), str(row.get("code_hash") or "")):
        col.update_one({"_id": row["_id"]}, {"$inc": {"attempts": 1}})
        raise ValueError("That code is wrong")
    col.delete_one({"_id": row["_id"]})


def clear_code(email: str, purpose: str) -> None:
    _codes().delete_one({"email": email, "purpose": purpose})


def _codes():
    from app.users import ensure_indexes

    ensure_indexes()
    return database()["auth_codes"]


def _still_fresh(row: dict, now: datetime) -> bool:
    created = row.get("created_at")
    expires = row.get("expires_at")
    if not isinstance(created, datetime) or not isinstance(expires, datetime):
        return False
    return expires > now and now - created < _COOLDOWN


def _digest(email: str, purpose: str, code: str) -> str:
    material = f"{purpose}:{email}:{code}".encode("utf-8")
    return hmac.new(auth_secret().encode("utf-8"), material, hashlib.sha256).hexdigest()
