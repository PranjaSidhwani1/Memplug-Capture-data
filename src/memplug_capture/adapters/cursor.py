"""Cursor hook payloads. Only the user prompt and the assistant reply are kept."""

from __future__ import annotations

from memplug_capture.redact import MESSAGE_LIMIT, clean_path, project_name, redact_text
from memplug_capture.schema import CaptureEvent, utc_now

SOURCE = "cursor"
_USER_EVENTS = {"beforesubmitprompt", "userpromptsubmit"}
_ASSISTANT_EVENTS = {"afteragentresponse", "agentresponse", "stop"}


def from_hook(payload: dict) -> list[CaptureEvent]:
    name = str(payload.get("hook_event_name") or "").replace("_", "").lower()
    if "thought" in name:
        return []
    session_id = str(payload.get("conversation_id") or payload.get("session_id") or "").strip()
    if not session_id:
        return []
    project = _project(payload)
    timestamp = utc_now()
    if name in _USER_EVENTS:
        return _message("user_message", _text(payload.get("prompt")), session_id, project, timestamp)
    if name in _ASSISTANT_EVENTS:
        text = _text(payload.get("text")) or _text(payload.get("last_assistant_message"))
        return _message("assistant_message", text, session_id, project, timestamp)
    return []


def _text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return redact_text(value, MESSAGE_LIMIT)


def _message(event_type: str, content: str, session_id: str, project: str, timestamp: str) -> list[CaptureEvent]:
    if not content:
        return []
    return [
        CaptureEvent(
            source=SOURCE,
            session_id=session_id,
            project=project,
            event_type=event_type,
            content=content,
            timestamp=timestamp,
            metadata={},
        )
    ]


def _project(payload: dict) -> str:
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        for root in roots:
            if isinstance(root, str) and root.strip():
                return project_name(clean_path(root))
    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        return project_name(cwd)
    return ""
