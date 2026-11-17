"""Extract memories at the token threshold, or after the idle window."""

from __future__ import annotations

import logging
import threading
import time

from app.config import checkpoint_tokens, meta_api_key, meta_model, postgres_url
from app.store import database

log = logging.getLogger("memplug.checkpoint")

_sweep_started = False


def token_count(text: str) -> int:
    return max(1, len(text) // 4)


def message_text(message: dict) -> str:
    """Text that counts toward a checkpoint, including a tool call and its result."""
    parts: list[str] = []
    tool_input = message.get("tool_input")
    content = message.get("content")
    if isinstance(tool_input, str) and tool_input.strip():
        parts.append(tool_input.strip())
    if isinstance(content, str) and content.strip():
        parts.append(content.strip())
    return "\n".join(parts)


def pending_token_count(messages: list[dict], start: int = 0) -> int:
    """Tokens in messages that have not been turned into a memory yet."""
    total = 0
    for message in messages[max(0, start) :]:
        if not isinstance(message, dict):
            continue
        text = message_text(message)
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
        text = message_text(message) if isinstance(message, dict) else ""
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
    """Captured messages are processed by the Postgres job worker."""
    return


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
