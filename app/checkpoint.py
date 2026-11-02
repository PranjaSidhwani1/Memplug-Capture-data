"""Extract memories at the token threshold, or after the idle window."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.config import checkpoint_idle_minutes, checkpoint_tokens, meta_api_key, meta_model, postgres_url
from app.store import database

log = logging.getLogger("memplug.checkpoint")

_STALE_AFTER = timedelta(minutes=15)
_sweep_started = False


def token_count(text: str) -> int:
    return max(1, len(text) // 4)


def pending_token_count(messages: list[dict], start: int = 0) -> int:
    """Tokens in messages that have not been turned into a memory yet."""
    total = 0
    for message in messages[max(0, start) :]:
        if not isinstance(message, dict):
            continue
        text = message.get("content") if isinstance(message.get("content"), str) else ""
        if text:
            total += token_count(text)
    return total


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
    """Start extraction on a full token window, or on the idle remainder."""
    if not meta_api_key() or not meta_model() or not postgres_url():
        return
    col = database()["conversations"]
    doc = col.find_one(
        key,
        {
            "messages": 1,
            "processed_messages": 1,
            "user_id": 1,
            "project": 1,
            "workspace_type": 1,
            "workspace_id": 1,
            "last_memory_at": 1,
            "updated_at": 1,
        },
    )
    if not doc:
        return
    user_id = str(doc.get("user_id") or key.get("user_id") or "").strip()
    if not user_id:
        return
    start = int(doc.get("processed_messages") or 0)
    pending = (doc.get("messages") or [])[start:]
    batch = take_batch(pending)
    reason = "tokens"
    if not batch and _idle_due(doc, pending):
        batch = pending
        reason = "idle"
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
        args=(
            dict(key),
            start,
            batch,
            user_id,
            str(doc.get("project") or ""),
            reason,
            str(doc.get("workspace_type") or "user"),
            str(doc.get("workspace_id") or user_id),
        ),
        daemon=True,
        name="memory-checkpoint",
    ).start()


def _run(
    key: dict,
    start: int,
    batch: list[dict],
    user_id: str,
    project: str,
    reason: str,
    workspace_type: str = "user",
    workspace_id: str = "",
) -> None:
    from app.extract import extract_memories
    from app.memories import save_memories

    col = database()["conversations"]
    try:
        log.info(
            "checkpoint start session=%s user=%s messages=%s reason=%s",
            key.get("session_id"),
            user_id,
            len(batch),
            reason,
        )
        memories = extract_memories(batch)
        saved = save_memories(
            user_id,
            str(key.get("source") or ""),
            str(key.get("session_id") or ""),
            project,
            memories,
            owner_type=workspace_type if workspace_type == "team" else "user",
            owner_id=workspace_id or user_id,
        )
        log.info("checkpoint done session=%s memories=%s", key.get("session_id"), saved)
        col.update_one(
            {**key, "$expr": {"$eq": [{"$ifNull": ["$processed_messages", 0]}, start]}},
            {
                "$set": {
                    "processed_messages": start + len(batch),
                    "extracting": False,
                    "last_memory_at": _now(),
                },
                "$unset": {"extracting_at": ""},
            },
        )
    except Exception:
        log.exception("memory checkpoint failed for %s", key.get("session_id"))
        col.update_one(key, {"$set": {"extracting": False}})
        return
    consider(key)


def start_idle_sweep() -> None:
    """Check once a minute for conversations whose last memory save is older than the idle window."""
    global _sweep_started
    if _sweep_started:
        return
    _sweep_started = True
    threading.Thread(target=_sweep_loop, daemon=True, name="memory-idle-sweep").start()


def _sweep_loop() -> None:
    while True:
        time.sleep(60)
        try:
            _sweep()
        except Exception:
            log.exception("idle sweep failed")


def _sweep() -> None:
    if not meta_api_key() or not meta_model() or not postgres_url():
        return
    col = database()["conversations"]
    for doc in col.find({}, {"user_id": 1, "source": 1, "session_id": 1}):
        source = doc.get("source")
        session_id = doc.get("session_id")
        if not source or not session_id:
            continue
        key = {"source": source, "session_id": session_id}
        if doc.get("user_id"):
            key["user_id"] = doc["user_id"]
        consider(key)


def _idle_due(doc: dict, pending: list[dict]) -> bool:
    if not pending:
        return False
    anchor = doc.get("last_memory_at") or (pending[0].get("timestamp") if isinstance(pending[0], dict) else None)
    if not isinstance(anchor, str) or not anchor:
        return False
    try:
        moment = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - moment >= timedelta(minutes=checkpoint_idle_minutes())


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
