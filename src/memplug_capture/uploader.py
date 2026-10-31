"""Send captured events to POST /v1/events. Failures stay in MongoDB."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from memplug_capture.config import api_settings
from memplug_capture.store import mark_uploaded, pending_uploads

_ROLES = {
    "user_message": "user",
    "assistant_message": "assistant",
    "tool_call": "tool",
    "tool_result": "tool",
    "session_start": "system",
    "session_end": "system",
}


def upload_pending(limit: int = 100) -> int:
    settings = api_settings()
    if not settings.configured:
        return 0
    sent = 0
    for row in pending_uploads(limit):
        event = row["body"]
        if isinstance(event, str):
            event = json.loads(event)
        ok = _post(settings.base_url, settings.api_key, event)
        mark_uploaded(row["idempotency_key"], ok)
        if ok:
            sent += 1
    return sent


def _post(base_url: str, api_key: str, event: dict) -> bool:
    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
    body = {
        "conversation_id": event.get("session_id"),
        "external_event_id": metadata.get("idempotency_key"),
        "event_type": event.get("event_type"),
        "speaker_role": _ROLES.get(str(event.get("event_type")), "system"),
        "content": event.get("content"),
        "occurred_at": event.get("timestamp"),
        "token_count": metadata.get("token_count", 0),
        "source": event.get("source"),
        "project": event.get("project"),
    }
    request = urllib.request.Request(
        f"{base_url}/v1/events",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": str(metadata.get("idempotency_key") or ""),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        return exc.code in {200, 201, 204, 409}
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
