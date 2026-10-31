"""Extract memories once a conversation has 1,000 new tokens."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.config import checkpoint_tokens, meta_api_key, meta_model, postgres_url
from app.store import database

log = logging.getLogger("memplug.checkpoint")

_STALE_AFTER = timedelta(minutes=15)


def token_count(text: str) -> int:
    return max(1, len(text) // 4)


def take_batch(messages: list[dict], limit: int | None = None) -> list[dict]:
    """Whole messages from the front of the list, stopping at the token limit."""
    if limit is None:
        limit = checkpoint_tokens()
    batch: list[dict] = []
    total = 0
    for message in messages:
        text = message.get("content") if isinstance(message.get("content"), str) else ""
        count = token_count(text)
        if batch and total >= limit:
            break
        batch.append(message)
        total += count
        if total >= limit:
            break
    if total < limit:
        return []
    return batch


def consider(key: dict) -> None:
    """Start extraction when this conversation has an unprocessed 1,000-token window."""
    if not meta_api_key() or not meta_model() or not postgres_url():
        return
    col = database()["conversations"]
    doc = col.find_one(key, {"messages": 1, "processed_messages": 1, "user_id": 1, "project": 1})
    if not doc:
        return
    user_id = str(doc.get("user_id") or key.get("user_id") or "").strip()
    if not user_id:
        return
    start = int(doc.get("processed_messages") or 0)
    messages = doc.get("messages") or []
    batch = take_batch(messages[start:])
    if not batch:
        return
    stale_before = (datetime.now(timezone.utc) - _STALE_AFTER).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    claimed = col.find_one_and_update(
        {
            **key,
            "$expr": {"$eq": [{"$ifNull": ["$processed_messages", 0]}, start]},
            "$or": [{"extracting": {"$ne": True}}, {"extracting_at": {"$lt": stale_before}}],
        },
        {"$set": {"extracting": True, "extracting_at": _now()}},
        return_document=ReturnDocument.AFTER,
    )
    if claimed is None:
        return
    threading.Thread(
        target=_run,
        args=(dict(key), start, batch, user_id, str(doc.get("project") or "")),
        daemon=True,
        name="memory-checkpoint",
    ).start()


def _run(key: dict, start: int, batch: list[dict], user_id: str, project: str) -> None:
    from app.extract import extract_memories
    from app.memories import save_memories

    col = database()["conversations"]
    try:
        log.info(
            "checkpoint start session=%s user=%s messages=%s",
            key.get("session_id"),
            user_id,
            len(batch),
        )
        memories = extract_memories(batch)
        saved = save_memories(
            user_id, str(key.get("source") or ""), str(key.get("session_id") or ""), project, memories
        )
        log.info("checkpoint done session=%s memories=%s", key.get("session_id"), saved)
        col.update_one(
            {**key, "$expr": {"$eq": [{"$ifNull": ["$processed_messages", 0]}, start]}},
            {
                "$set": {"processed_messages": start + len(batch), "extracting": False},
                "$unset": {"extracting_at": ""},
            },
        )
    except Exception:
        log.exception("memory checkpoint failed for %s", key.get("session_id"))
        col.update_one(key, {"$set": {"extracting": False}})
        return
    consider(key)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
