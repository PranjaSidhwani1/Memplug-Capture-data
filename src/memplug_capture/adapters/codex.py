"""Codex command hooks.

The stdin shape is close to Claude Code, but transcript_path may be null
and the transcript format is not stable. This adapter uses only the hook
fields: prompt, tool_name, tool_input, tool_response, last_assistant_message,
and model. Transcript catch-up is a separate, tolerant reader.
"""

from __future__ import annotations

from memplug_capture.redact import MESSAGE_LIMIT, TOOL_LIMIT, project_name, redact_text, stringify
from memplug_capture.schema import CaptureEvent, utc_now

SOURCE = "codex"


def from_hook(payload: dict) -> list[CaptureEvent]:
    event_name = str(payload.get("hook_event_name") or "")
    session_id = str(payload.get("session_id") or "unknown")
    project = project_name(payload.get("cwd") if isinstance(payload.get("cwd"), str) else "")
    timestamp = utc_now()
    model = payload.get("model") if isinstance(payload.get("model"), str) else ""
    base: dict = {"model": model} if model else {}
    turn_id = payload.get("turn_id")
    if isinstance(turn_id, str) and turn_id:
        base["turn_id"] = turn_id

    if event_name == "SessionStart":
        return [_event("session_start", "session started", session_id, project, timestamp, {**base, "source_id": "session_start"})]
    if event_name == "SessionEnd":
        return [_event("session_end", "session ended", session_id, project, timestamp, {**base, "source_id": "session_end"})]
    if event_name == "UserPromptSubmit":
        prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
        text = redact_text(prompt, MESSAGE_LIMIT)
        if not text:
            return []
        source_id = str(turn_id or "")
        meta = dict(base)
        if source_id:
            meta["source_id"] = source_id
        return [_event("user_message", text, session_id, project, timestamp, meta)]
    if event_name == "PostToolUse":
        return _tools(payload, session_id, project, timestamp, base)
    if event_name == "Stop" and not payload.get("stop_hook_active"):
        text = payload.get("last_assistant_message")
        if not isinstance(text, str) or not text.strip():
            return []
        meta = dict(base)
        if isinstance(turn_id, str) and turn_id:
            meta["source_id"] = turn_id
        return [_event("assistant_message", redact_text(text, MESSAGE_LIMIT), session_id, project, timestamp, meta)]
    return []


def _tools(payload: dict, session_id: str, project: str, timestamp: str, base: dict) -> list[CaptureEvent]:
    name = str(payload.get("tool_name") or "tool")
    tool_id = str(payload.get("tool_use_id") or "")
    meta = {**base, "tool_name": name}
    if tool_id:
        meta["tool_use_id"] = tool_id
    call_meta = {**meta, "source_id": tool_id or name}
    events = [
        _event(
            "tool_call",
            stringify({"name": name, "input": payload.get("tool_input")}, TOOL_LIMIT) or name,
            session_id,
            project,
            timestamp,
            call_meta,
        )
    ]
    result = stringify(payload.get("tool_response"), TOOL_LIMIT)
    if result:
        events.append(
            _event(
                "tool_result",
                result,
                session_id,
                project,
                timestamp,
                {**meta, "source_id": f"{tool_id or name}:result"},
            )
        )
    return events


def _event(
    event_type: str,
    content: str,
    session_id: str,
    project: str,
    timestamp: str,
    metadata: dict,
) -> CaptureEvent:
    return CaptureEvent(
        source=SOURCE,
        session_id=session_id,
        project=project,
        event_type=event_type,
        content=content,
        timestamp=timestamp,
        metadata=dict(metadata),
    )
