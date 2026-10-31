"""One adapter per coding agent. Payloads are not interchangeable."""

from memplug_capture.adapters.claude_code import from_hook as from_claude_code
from memplug_capture.adapters.codex import from_hook as from_codex
from memplug_capture.adapters.cursor import from_hook as from_cursor
from memplug_capture.schema import CaptureEvent

_ADAPTERS = {
    "claude_code": from_claude_code,
    "codex": from_codex,
    "cursor": from_cursor,
}


def events_from_hook(source: str, payload: dict) -> list[CaptureEvent]:
    adapter = _ADAPTERS.get(source)
    if adapter is None or not isinstance(payload, dict):
        return []
    return adapter(payload)
