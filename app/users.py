from __future__ import annotations

from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo.errors import DuplicateKeyError

from app.security import (
    hash_api_key,
    hash_password,
    new_api_key,
    open_api_key,
    password_matches,
    seal_api_key,
)
from app.store import database

_ready = False
_KEY_LIMIT = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_indexes() -> None:
    global _ready
    if _ready:
        return
    db = database()
    db["users"].create_index("email", unique=True)
    keys = db["api_keys"]
    keys.create_index("key_hash", unique=True)
    keys.create_index([("user_id", 1), ("revoked_at", 1)])
    _ready = True


def _users():
    ensure_indexes()
    return database()["users"]


def _keys():
    ensure_indexes()
    return database()["api_keys"]


def public_user(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "email": doc["email"],
        "name": doc.get("name") or "",
        "created_at": doc.get("created_at") or "",
    }


def create_user(email: str, password: str, name: str) -> dict:
    salt, digest = hash_password(password)
    document = {
        "email": email,
        "name": name,
        "password_salt": salt,
        "password_hash": digest,
        "created_at": _now(),
    }
    try:
        result = _users().insert_one(document)
    except DuplicateKeyError as exc:
        raise ValueError("An account with that email already exists") from exc
    document["_id"] = result.inserted_id
    return public_user(document)


_DUMMY_SALT, _DUMMY_HASH = hash_password("memplug-placeholder")


def authenticate(email: str, password: str) -> dict | None:
    doc = _users().find_one({"email": email})
    if not doc:
        password_matches(password, _DUMMY_SALT, _DUMMY_HASH)
        return None
    if not password_matches(password, doc["password_salt"], doc["password_hash"]):
        return None
    return public_user(doc)


def get_user(user_id: str) -> dict | None:
    try:
        oid = ObjectId(user_id)
    except InvalidId:
        return None
    doc = _users().find_one({"_id": oid})
    return public_user(doc) if doc else None


def create_api_key(user_id: str, name: str) -> dict:
    col = _keys()
    active = col.count_documents({"user_id": user_id, "revoked_at": None})
    if active >= _KEY_LIMIT:
        raise ValueError("Revoke a key first. Eight active keys is the limit.")
    raw = new_api_key()
    document = {
        "user_id": user_id,
        "name": name,
        "prefix": raw[:11],
        "key_hash": hash_api_key(raw),
        "key_enc": seal_api_key(raw),
        "created_at": _now(),
        "revoked_at": None,
    }
    result = col.insert_one(document)
    return {
        "id": str(result.inserted_id),
        "name": name,
        "prefix": document["prefix"],
        "key": raw,
        "created_at": document["created_at"],
    }


def list_api_keys(user_id: str) -> list[dict]:
    rows = _keys().find({"user_id": user_id, "revoked_at": None}).sort("created_at", -1)
    return [
        {
            "id": str(row["_id"]),
            "name": row.get("name") or "default",
            "prefix": row.get("prefix") or "",
            "created_at": row.get("created_at") or "",
        }
        for row in rows
    ]


def revoke_api_key(user_id: str, key_id: str) -> bool:
    try:
        oid = ObjectId(key_id)
    except InvalidId:
        return False
    result = _keys().update_one(
        {"_id": oid, "user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": _now()}},
    )
    return result.modified_count == 1


def reveal_api_key(user_id: str, key_id: str) -> dict | None:
    try:
        oid = ObjectId(key_id)
    except InvalidId:
        return None
    row = _keys().find_one({"_id": oid, "user_id": user_id, "revoked_at": None})
    if not row:
        return None
    return {"id": str(row["_id"]), "name": row.get("name") or "default", "key": open_api_key(row["key_enc"])}


def user_id_for_api_key(raw: str) -> str | None:
    row = _keys().find_one({"key_hash": hash_api_key(raw), "revoked_at": None}, {"user_id": 1})
    if not row:
        return None
    return str(row["user_id"])
