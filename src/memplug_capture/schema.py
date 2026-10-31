"""Unified capture event. Raw events stay in this shape until ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

SOURCES = frozenset({"claude_code", "codex", "cursor"})
EVENT_TYPES = frozenset(
    {
        "user_message",
        "assistant_message",
        "tool_call",
        "tool_result",
        "session_start",
        "session_end",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def content_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass
class CaptureEvent:
    source: str
    session_id: str
    project: str
    event_type: str
    content: str
    timestamp: str
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError(f"unknown source {self.source}")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event type {self.event_type}")
        self.metadata.setdefault("token_count", max(1, len(self.content) // 4) if self.content else 0)
        self.metadata.setdefault("token_count_estimated", True)
        identity = self.metadata.get("source_id") or content_hash(self.content)
        self.metadata["idempotency_key"] = f"{self.source}:{self.session_id}:{self.event_type}:{identity}"
        self.metadata["content_hash"] = content_hash(self.content)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "session_id": self.session_id,
            "project": self.project,
            "event_type": self.event_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }
