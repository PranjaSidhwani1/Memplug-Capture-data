from __future__ import annotations

import secrets
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
    db["teams"].create_index("created_by")
    db["teams"].create_index("join_code", unique=True)
    members = db["team_members"]
    members.create_index([("team_id", 1), ("user_id", 1)], unique=True)
    members.create_index("user_id")
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


def create_api_key(user_id: str, name: str, team_id: str | None = None) -> dict:
    col = _keys()
    active = col.count_documents({"user_id": user_id, "revoked_at": None})
    if active >= _KEY_LIMIT:
        raise ValueError("Revoke a key first. Eight active keys is the limit.")
    if team_id:
        if not member_of_team(user_id, team_id):
            raise ValueError("Join that team before creating a key for it")
        workspace_type = "team"
        workspace_id = team_id
    else:
        workspace_type = "user"
        workspace_id = user_id
    raw = new_api_key()
    document = {
        "user_id": user_id,
        "name": name,
        "prefix": raw[:11],
        "key_hash": hash_api_key(raw),
        "key_enc": seal_api_key(raw),
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "created_at": _now(),
        "revoked_at": None,
    }
    result = col.insert_one(document)
    return {
        "id": str(result.inserted_id),
        "name": name,
        "prefix": document["prefix"],
        "key": raw,
        "workspace_type": workspace_type,
        "workspace_id": workspace_id,
        "created_at": document["created_at"],
    }


def list_api_keys(user_id: str) -> list[dict]:
    rows = _keys().find({"user_id": user_id, "revoked_at": None}).sort("created_at", -1)
    return [
        {
            "id": str(row["_id"]),
            "name": row.get("name") or "default",
            "prefix": row.get("prefix") or "",
            "workspace_type": row.get("workspace_type") or "user",
            "workspace_id": row.get("workspace_id") or user_id,
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


def _teams():
    ensure_indexes()
    return database()["teams"]


def _members():
    ensure_indexes()
    return database()["team_members"]


def create_team(user_id: str, name: str) -> dict:
    cleaned = " ".join(name.split())[:80]
    if not cleaned:
        raise ValueError("Enter a team name")
    code = secrets.token_hex(4).upper()
    result = _teams().insert_one(
        {"name": cleaned, "join_code": code, "created_by": user_id, "created_at": _now()}
    )
    team_id = str(result.inserted_id)
    _members().insert_one(
        {"team_id": team_id, "user_id": user_id, "role": "owner", "created_at": _now()}
    )
    return {"id": team_id, "name": cleaned, "role": "owner", "join_code": code}


def join_team(user_id: str, code: str) -> dict:
    cleaned = "".join(code.split()).upper()
    if not cleaned:
        raise ValueError("Enter a join code")
    team = _teams().find_one({"join_code": cleaned})
    if not team:
        raise ValueError("That join code does not match a team")
    team_id = str(team["_id"])
    existing = _members().find_one({"team_id": team_id, "user_id": user_id})
    if not existing:
        _members().insert_one(
            {"team_id": team_id, "user_id": user_id, "role": "member", "created_at": _now()}
        )
        role = "member"
    else:
        role = existing.get("role") or "member"
    return {
        "id": team_id,
        "name": team.get("name") or "Team",
        "role": role,
        "join_code": (team.get("join_code") or "") if role == "owner" else "",
    }


def list_teams(user_id: str) -> list[dict]:
    teams: list[dict] = []
    for member in _members().find({"user_id": user_id}):
        try:
            oid = ObjectId(member.get("team_id"))
        except InvalidId:
            continue
        team = _teams().find_one({"_id": oid})
        if not team:
            continue
        role = member.get("role") or "member"
        teams.append(
            {
                "id": str(team["_id"]),
                "name": team.get("name") or "Team",
                "role": role,
                "join_code": (team.get("join_code") or "") if role == "owner" else "",
            }
        )
    teams.sort(key=lambda item: item["name"].casefold())
    return teams


def leave_team(user_id: str, team_id: str) -> bool:
    member = _members().find_one({"team_id": team_id, "user_id": user_id})
    if not member:
        return False
    if member.get("role") == "owner":
        raise ValueError("The owner stays with the team")
    _members().delete_one({"_id": member["_id"]})
    return True


def member_of_team(user_id: str, team_id: str) -> bool:
    if not user_id or not team_id:
        return False
    ensure_indexes()
    return (
        database()["team_members"].find_one({"team_id": team_id, "user_id": user_id}, {"_id": 1})
        is not None
    )


def workspace_for_api_key(raw: str) -> dict | None:
    row = _keys().find_one(
        {"key_hash": hash_api_key(raw), "revoked_at": None},
        {"user_id": 1, "workspace_type": 1, "workspace_id": 1},
    )
    if not row:
        return None
    user_id = str(row["user_id"])
    kind = row.get("workspace_type") or "user"
    owner_id = str(row.get("workspace_id") or user_id)
    if kind != "team":
        return {"user_id": user_id, "workspace_type": "user", "workspace_id": user_id}
    if not member_of_team(user_id, owner_id):
        return None
    return {"user_id": user_id, "workspace_type": "team", "workspace_id": owner_id}


def user_id_for_api_key(raw: str) -> str | None:
    space = workspace_for_api_key(raw)
    return space["user_id"] if space else None
