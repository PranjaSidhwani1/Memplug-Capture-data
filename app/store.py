from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

# PyOpenSSL's certificate helper calls an API removed by current cryptography.
# A failed import makes PyMongo use the standard-library TLS stack instead.
sys.modules.setdefault("pymongo.pyopenssl_context", None)

import certifi
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from app.config import mongo_db, mongo_uri

log = logging.getLogger("memplug.store")

_client: MongoClient | None = None
_ready = False


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def database():
    global _client
    if _client is None:
        _client = MongoClient(
            mongo_uri(),
            serverSelectionTimeoutMS=10000,
            tz_aware=True,
            tlsCAFile=certifi.where(),
        )
    return _client[mongo_db()]


def _ensure_conversation_index(col) -> None:
    for name, spec in col.index_information().items():
        if spec.get("unique") and spec.get("key") == [("source", 1), ("session_id", 1)]:
            col.drop_index(name)
    col.create_index(
        [("user_id", 1), ("source", 1), ("session_id", 1)],
        unique=True,
        name="user_source_session",
    )


def ensure_store_indexes() -> None:
    _collection()


def _collection():
    global _ready
    col = database()["conversations"]
    if not _ready:
        _ensure_conversation_index(col)
        _ready = True
    return col


def save_message(
    source: str,
    session_id: str,
    project: str,
    role: str,
    content: str,
    timestamp: str | None = None,
    user_id: str | None = None,
) -> bool:
    text = content.strip()
    if not text or role not in {"user", "assistant"}:
        return False
    col = _collection()
    key = {"source": source, "session_id": session_id}
    if user_id:
        key["user_id"] = user_id
    message = {"role": role, "content": text, "timestamp": timestamp or _now()}
    existing = col.find_one(key, {"messages": 1})
    if existing:
        for saved in existing.get("messages") or []:
            if saved.get("role") == role and saved.get("content") == text:
                log.info(
                    "mongo skipped duplicate source=%s session=%s user=%s role=%s",
                    source,
                    session_id,
                    user_id or "",
                    role,
                )
                return False
        col.update_one(
            key,
            {"$set": {"project": project, "updated_at": _now()}, "$push": {"messages": message}},
        )
    else:
        try:
            col.insert_one(
                {
                    **key,
                    "project": project,
                    "created_at": _now(),
                    "updated_at": _now(),
                    "messages": [message],
                }
            )
        except DuplicateKeyError:
            col.update_one(
                key,
                {"$set": {"project": project, "updated_at": _now()}, "$push": {"messages": message}},
            )
    log.info(
        "mongo saved source=%s session=%s user=%s project=%s role=%s content=%s",
        source,
        session_id,
        user_id or "",
        project,
        role,
        text,
    )
    try:
        from app.checkpoint import consider

        consider(key)
    except Exception:
        log.exception("memory checkpoint was not started")
    return True


def stats(user_id: str | None = None) -> dict[str, int]:
    col = _collection()
    query = {"user_id": user_id} if user_id else {}
    conversations = col.count_documents(query)
    messages = 0
    for doc in col.find(query, {"messages": 1}):
        messages += len(doc.get("messages") or [])
    return {"conversations": conversations, "messages": messages}
