"""Claude Code command hooks.

Handles UserPromptSubmit, PostToolUse, Stop, SessionStart, and SessionEnd.
The transcript file can lag the current turn, so the prompt, tool payload,
and last_assistant_message are taken from the hook itself.
"""

from __future__ import annotations

from memplug_capture.redact import MESSAGE_LIMIT, TOOL_LIMIT, project_name, redact_text, stringify
from memplug_capture.schema import CaptureEvent, utc_now

SOURCE = "claude_code"


def from_hook(payload: dict) -> list[CaptureEvent]:
    event_name = str(payload.get("hook_event_name") or "")
    session_id = str(payload.get("session_id") or "unknown")
    project = project_name(payload.get("cwd") if isinstance(payload.get("cwd"), str) else "")
    timestamp = utc_now()
    model = payload.get("model") if isinstance(payload.get("model"), str) else ""
    base = {"model": model} if model else {}

    if event_name == "SessionStart":
        return [_lifecycle("session_start", "session started", session_id, project, timestamp, base)]
    if event_name == "SessionEnd":
        return [_lifecycle("session_end", "session ended", session_id, project, timestamp, base)]
    if event_name == "UserPromptSubmit":
        prompt = payload.get("prompt")
        if not isinstance(prompt, str):
            prompt = payload.get("userPrompt") if isinstance(payload.get("userPrompt"), str) else ""
        text = redact_text(prompt, MESSAGE_LIMIT)
        if not text:
            return []
        source_id = str(payload.get("prompt_id") or "")
        return [
            _message(
                "user_message",
                text,
                session_id,
                project,
                timestamp,
                {**base, "source_id": source_id} if source_id else base,
            )
        ]
    if event_name == "PostToolUse":
        return _tool_events(payload, session_id, project, timestamp, base)
    if event_name == "Stop" and not payload.get("stop_hook_active"):
        text = payload.get("last_assistant_message")
        if not isinstance(text, str) or not text.strip():
            return []
        return [
            _message(
                "assistant_message",
                redact_text(text, MESSAGE_LIMIT),
                session_id,
                project,
                timestamp,
                base,
            )
        ]
    return []


def _tool_events(payload: dict, session_id: str, project: str, timestamp: str, base: dict) -> list[CaptureEvent]:
    name = str(payload.get("tool_name") or "tool")
    tool_id = str(payload.get("tool_use_id") or "")
    call = stringify({"name": name, "input": payload.get("tool_input")}, TOOL_LIMIT)
    result = stringify(payload.get("tool_response"), TOOL_LIMIT)
    meta = {**base, "tool_name": name}
    if tool_id:
        meta["tool_use_id"] = tool_id
    events = [
        _message(
            "tool_call",
            call or name,
            session_id,
            project,
            timestamp,
            {**meta, "source_id": tool_id or name},
        )
    ]
    if result:
        events.append(
            _message(
                "tool_result",
                result,
                session_id,
                project,
                timestamp,
                {**meta, "source_id": f"{tool_id or name}:result"},
            )
        )
    return events


def _lifecycle(event_type: str, content: str, session_id: str, project: str, timestamp: str, base: dict) -> CaptureEvent:
    return _message(event_type, content, session_id, project, timestamp, {**base, "source_id": event_type})


def _message(
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
