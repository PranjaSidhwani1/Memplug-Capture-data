"""Save a conversation via the deployed Capture API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from memplug_capture.config import api_settings


def fetch_stats() -> dict:
    settings = api_settings()
    if not settings.configured:
        return {"error": "Set MEMPLUG_API_URL and MEMPLUG_API_KEY"}
    request = urllib.request.Request(
        f"{settings.base_url}/v1/capture/stats",
        headers={"Authorization": f"Bearer {settings.api_key}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        return {"error": str(exc)}
