"""Incremental, version-tolerant transcript reader.

The on-disk shape differs by agent and by version. Unknown fields are
ignored. Records that are not JSON objects are skipped. Thinking blocks
are never returned.
"""

from __future__ import annotations

import json
from pathlib import Path

from memplug_capture.redact import MESSAGE_LIMIT, TOOL_LIMIT, redact_text, stringify, text_from_content
from memplug_capture.schema import CaptureEvent, utc_now
from memplug_capture.store import offset_for, save_offset

_TOOL_USE = frozenset({"tool_use", "tool_call", "function_call"})
_TOOL_RESULT = frozenset({"tool_result", "tool_result_block"})


def read_new_records(path_value: str | None) -> list[dict]:
    if not path_value or not isinstance(path_value, str):
        return []
    path = Path(path_value).expanduser()
    if not path.is_file():
        return []
    key = str(path)
    offset = offset_for(key)
    size = path.stat().st_size
    if size < offset:
        offset = 0
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    if not data:
        return []
    if not data.endswith(b"\n"):
        cut = data.rfind(b"\n")
        if cut < 0:
            return []
        data = data[: cut + 1]
    records: list[dict] = []
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json_loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    save_offset(key, offset + len(data))
    return records


def json_loads(raw: bytes) -> object:
    return json.loads(raw.decode("utf-8"))


def events_from_records(
    records: list[dict],
    *,
    source: str,
    session_id: str,
    project: str,
    model: str = "",
) -> list[CaptureEvent]:
    events: list[CaptureEvent] = []
    for record in records:
        events.extend(
            _from_record(record, source=source, session_id=session_id, project=project, model=model)
        )
    return events


def _from_record(
    record: dict,
    *,
    source: str,
    session_id: str,
    project: str,
    model: str,
) -> list[CaptureEvent]:
    kind = str(record.get("type") or "")
    if kind in {"thinking", "redacted_thinking", "reasoning", "progress", "system"}:
        return []
    message = record.get("message") if isinstance(record.get("message"), dict) else record
    role = str(message.get("role") or record.get("role") or kind)
    if role in {"thinking", "reasoning"}:
        return []
    timestamp = _timestamp(record)
    record_session = str(record.get("sessionId") or record.get("session_id") or session_id)
    record_id = str(record.get("uuid") or record.get("id") or "")
    meta = {"model": model} if model else {}
    content = message.get("content", record.get("content"))
    events: list[CaptureEvent] = []

    if isinstance(content, list):
        visible = text_from_content(content)
        if visible and role in {"user", "assistant", "human"}:
            events.append(
                _event(
                    source=source,
                    session_id=record_session,
                    project=project,
                    event_type="user_message" if role in {"user", "human"} else "assistant_message",
                    content=redact_text(visible, MESSAGE_LIMIT),
                    timestamp=timestamp,
                    source_id=record_id,
                    metadata=meta,
                )
            )
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            events.extend(
                _from_block(
                    block,
                    source=source,
                    session_id=record_session,
                    project=project,
                    timestamp=timestamp,
                    fallback_id=f"{record_id}:{index}" if record_id else "",
                    metadata=meta,
                )
            )
        return events

    visible = text_from_content(content) if not isinstance(content, str) else content
    if visible and role in {"user", "human"}:
        events.append(
            _event(
                source=source,
                session_id=record_session,
                project=project,
                event_type="user_message",
                content=redact_text(visible, MESSAGE_LIMIT),
                timestamp=timestamp,
                source_id=record_id,
                metadata=meta,
            )
        )
    elif visible and role == "assistant":
        events.append(
            _event(
                source=source,
                session_id=record_session,
                project=project,
                event_type="assistant_message",
                content=redact_text(visible, MESSAGE_LIMIT),
                timestamp=timestamp,
                source_id=record_id,
                metadata=meta,
            )
        )
    return events


def _from_block(
    block: dict,
    *,
    source: str,
    session_id: str,
    project: str,
    timestamp: str,
    fallback_id: str,
    metadata: dict,
) -> list[CaptureEvent]:
    block_type = str(block.get("type") or "")
    if block_type in _TOOL_USE or (not block_type and block.get("name") and "input" in block):
        tool_id = str(block.get("id") or block.get("tool_use_id") or fallback_id)
        name = str(block.get("name") or "tool")
        rendered = stringify({"name": name, "input": block.get("input")}, TOOL_LIMIT)
        return [
            _event(
                source=source,
                session_id=session_id,
                project=project,
                event_type="tool_call",
                content=rendered,
                timestamp=timestamp,
                source_id=tool_id or fallback_id,
                metadata={**metadata, "tool_name": name, "tool_use_id": tool_id},
            )
        ]
    if block_type in _TOOL_RESULT or (not block_type and block.get("tool_use_id") and "content" in block):
        tool_id = str(block.get("tool_use_id") or block.get("id") or fallback_id)
        rendered = stringify(block.get("content"), TOOL_LIMIT)
        if not rendered:
            return []
        return [
            _event(
                source=source,
                session_id=session_id,
                project=project,
                event_type="tool_result",
                content=rendered,
                timestamp=timestamp,
                source_id=f"{tool_id}:result",
                metadata={**metadata, "tool_use_id": tool_id},
            )
        ]
    return []


def _event(
    *,
    source: str,
    session_id: str,
    project: str,
    event_type: str,
    content: str,
    timestamp: str,
    source_id: str,
    metadata: dict,
) -> CaptureEvent:
    meta = dict(metadata)
    if source_id:
        meta["source_id"] = source_id
    return CaptureEvent(
        source=source,
        session_id=session_id or "unknown",
        project=project,
        event_type=event_type,
        content=content,
        timestamp=timestamp,
        metadata=meta,
    )


def _timestamp(record: dict) -> str:
    for key in ("timestamp", "created_at", "occurred_at"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return utc_now()
