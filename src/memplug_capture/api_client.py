"""POST captured messages to the deployed Memplug Capture API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from memplug_capture.config import api_settings


def save_message(
    source: str,
    session_id: str,
    project: str,
    role: str,
    content: str,
    timestamp: str,
) -> int:
    settings = api_settings()
    if not settings.configured:
        raise RuntimeError("Set MEMPLUG_API_URL and MEMPLUG_API_KEY in capture/.env")

    body = json.dumps(
        {
            "source": source,
            "session_id": session_id,
            "project": project,
            "role": role,
            "content": content,
            "timestamp": timestamp,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{settings.base_url}/v1/capture/message",
        data=body,
        headers={
            "Authorization": f"Bearer {settings.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return 1 if payload.get("saved") else 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"capture API returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"capture API unreachable: {exc.reason}") from exc
