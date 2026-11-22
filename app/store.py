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
    col.create_index([("workspace_type", 1), ("workspace_id", 1)], name="workspace")


def ensure_store_indexes() -> None:
    _collection()


def _collection():
    global _ready
    col = database()["conversations"]
    if not _ready:
        _ensure_conversation_index(col)
        _ready = True
    return col


def _same_message(saved: dict, message: dict) -> bool:
    if not isinstance(saved, dict):
        return False
    if saved.get("role") != message.get("role") or saved.get("content") != message.get("content"):
        return False
    if message.get("role") != "tool":
        return True
    return (
        (saved.get("tool_use_id") or "") == (message.get("tool_use_id") or "")
        and (saved.get("tool_name") or "") == (message.get("tool_name") or "")
        and (saved.get("tool_input") or "") == (message.get("tool_input") or "")
    )


def save_message(
    source: str,
    session_id: str,
    project: str,
    role: str,
    content: str,
    timestamp: str | None = None,
    user_id: str | None = None,
    workspace_type: str = "user",
    workspace_id: str = "",
    tool_name: str = "",
    tool_use_id: str = "",
    tool_input: str = "",
    tool_status: str = "",
    event_id: str = "",
    external_message_id: str = "",
) -> bool:
    text = content.strip()
    if not text or role not in {"user", "assistant", "tool"}:
        return False
    col = _collection()
    key = {"source": source, "session_id": session_id}
    if user_id:
        key["user_id"] = user_id
    message = {"role": role, "content": text, "timestamp": timestamp or _now(), "saved_at": _now()}
    if role == "tool":
        message["tool_name"] = tool_name.strip()
        message["tool_use_id"] = tool_use_id.strip()
        message["tool_input"] = tool_input.strip()
        message["tool_status"] = tool_status.strip() or "ok"
    kind = workspace_type if workspace_type in {"user", "team"} else "user"
    owner = workspace_id or user_id or ""
    if kind == "user":
        owner = user_id or owner
    existing = col.find_one(key, {"messages": 1})
    if existing:
        for saved in existing.get("messages") or []:
            if _same_message(saved, message):
                log.info(
                    "mongo skipped duplicate source=%s session=%s user=%s role=%s",
                    source,
                    session_id,
                    user_id or "",
                    role,
                )
                _record_for(
                    message,
                    user_id=user_id or "",
                    workspace_type=kind,
                    workspace_id=owner,
                    source=source,
                    session_id=session_id,
                    project_id=project,
                    role=role,
                    content=text,
                    event_id=event_id,
                    external_message_id=external_message_id,
                )
                return False
        col.update_one(
            key,
            {
                "$set": {
                    "project": project,
                    "workspace_type": kind,
                    "workspace_id": owner,
                    "updated_at": _now(),
                },
                "$push": {"messages": message},
            },
        )
    else:
        try:
            col.insert_one(
                {
                    **key,
                    "project": project,
                    "workspace_type": kind,
                    "workspace_id": owner,
                    "created_at": _now(),
                    "updated_at": _now(),
                    "messages": [message],
                }
            )
        except DuplicateKeyError:
            col.update_one(
                key,
                {
                    "$set": {
                        "project": project,
                    "workspace_type": kind,
                    "workspace_id": owner,
                        "updated_at": _now(),
                    },
                    "$push": {"messages": message},
                },
            )
    log.info(
        "mongo saved source=%s session=%s user=%s project=%s role=%s tool=%s content=%s",
        source,
        session_id,
        user_id or "",
        project,
        role,
        message.get("tool_name") or "",
        text,
    )
    if role == "assistant":
        log.info("assistant output session=%s\n%s", session_id, text)
    doc = col.find_one(key, {"messages": 1, "processed_messages": 1}) or {}
    from app.checkpoint import pending_token_count
    from app.config import checkpoint_tokens

    start = int(doc.get("processed_messages") or 0)
    pending = pending_token_count(doc.get("messages") or [], start)
    log.info(
        "pending tokens since last memory source=%s session=%s tokens=%s limit=%s",
        source,
        session_id,
        pending,
        checkpoint_tokens(),
    )
    _record_for(
        message,
        user_id=user_id or "",
        workspace_type=kind,
        workspace_id=owner,
        source=source,
        session_id=session_id,
        project_id=project,
        role=role,
        content=text,
        event_id=event_id,
        external_message_id=external_message_id,
    )
    return True


def _record_for(message: dict, **fields) -> None:
    try:
        from app.ingest import record_captured_message

        record_captured_message(
            timestamp=message["timestamp"],
            tool_name=message.get("tool_name") or "",
            tool_use_id=message.get("tool_use_id") or "",
            tool_input=message.get("tool_input") or "",
            tool_status=message.get("tool_status") or "",
            **fields,
        )
    except Exception:
        log.exception("message was not copied into postgres")


def stats(user_id: str | None = None) -> dict[str, int]:
    col = _collection()
    query = {"user_id": user_id} if user_id else {}
    conversations = col.count_documents(query)
    messages = 0
    for doc in col.find(query, {"messages": 1}):
        messages += len(doc.get("messages") or [])
    return {"conversations": conversations, "messages": messages}
