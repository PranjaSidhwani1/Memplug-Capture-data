"""Hook entry. Save the user prompt and assistant reply, then return."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from memplug_capture.adapters import events_from_hook
from memplug_capture.config import capture_allowed
from memplug_capture.schema import SOURCES
from memplug_capture.api_client import save_message

_ERROR_LOG = Path(__file__).resolve().parents[2] / "hook-error.log"

_ROLES = {"user_message": "user", "assistant_message": "assistant"}


def run_hook(source: str) -> int:
    if source not in SOURCES:
        return 0
    if not capture_allowed():
        return 0
    raw = sys.stdin.buffer.read()
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        for event in events_from_hook(source, payload):
            role = _ROLES.get(event.event_type)
            if role is None:
                continue
            save_message(event.source, event.session_id, event.project, role, event.content, event.timestamp)
    except (Exception, SystemExit):
        _log_failure()
        return 0
    return 0


def _log_failure() -> None:
    try:
        with _ERROR_LOG.open("a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc() + "\n")
    except OSError:
        return
