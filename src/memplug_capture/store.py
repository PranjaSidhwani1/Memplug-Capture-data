"""Save a conversation in MongoDB. One document per session."""

from __future__ import annotations

import certifi
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError

from memplug_capture.config import mongo_settings
from memplug_capture.schema import utc_now

_CLIENT: MongoClient | None = None
_READY = False


def _mongo_client(uri: str) -> MongoClient:
    return MongoClient(
        uri,
        serverSelectionTimeoutMS=8000,
        tz_aware=True,
        tlsCAFile=certifi.where(),
    )


def _conversations():
    global _CLIENT, _READY
    if _CLIENT is None:
        uri, name = mongo_settings()
        _CLIENT = _mongo_client(uri)
        database = _CLIENT[name]
    else:
        _, name = mongo_settings()
        database = _CLIENT[name]
    collection = database["conversations"]
    if not _READY:
        collection.create_index([("source", 1), ("session_id", 1)], unique=True)
        _READY = True
    return collection


def save_message(source: str, session_id: str, project: str, role: str, content: str, timestamp: str) -> int:
    """Append one user or assistant message. Skip an exact duplicate."""
    text = content.strip()
    if not text or role not in {"user", "assistant"}:
        return 0
    collection = _conversations()
    key = {"source": source, "session_id": session_id}
    existing = collection.find_one(key, {"messages": 1})
    message = {"role": role, "content": text, "timestamp": timestamp or utc_now()}
    if existing:
        for saved in existing.get("messages") or []:
            if saved.get("role") == role and saved.get("content") == text:
                return 0
        collection.update_one(
            key,
            {"$set": {"project": project, "updated_at": utc_now()}, "$push": {"messages": message}},
        )
        return 1
    try:
        collection.insert_one(
            {
                **key,
                "project": project,
                "created_at": utc_now(),
                "updated_at": utc_now(),
                "messages": [message],
            }
        )
    except DuplicateKeyError:
        collection.update_one(
            key,
            {"$set": {"project": project, "updated_at": utc_now()}, "$push": {"messages": message}},
        )
    return 1


def counts() -> dict[str, int]:
    collection = _conversations()
    conversations = collection.count_documents({})
    messages = 0
    for doc in collection.find({}, {"messages": 1}):
        messages += len(doc.get("messages") or [])
    return {"conversations": conversations, "messages": messages}
