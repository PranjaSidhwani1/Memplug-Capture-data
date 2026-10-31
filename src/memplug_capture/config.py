"""Capture switch and paths. Identity is never taken from a transcript."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

ENABLED = "enabled"
PAUSED = "paused"
DISABLED = "disabled"


def load_env() -> None:
    """Load the first .env file found. Existing environment variables win."""
    candidates: list[Path] = []
    explicit = os.environ.get("MEMPLUG_ENV_FILE", "").strip()
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parents[2] / ".env")
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        return


def capture_root() -> Path:
    return Path(__file__).resolve().parents[2]


def capture_dir() -> Path:
    raw = os.environ.get("MEMPLUG_CAPTURE_DIR", "").strip()
    path = Path(raw) if raw else Path.home() / ".memplug" / "capture"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path() -> Path:
    return capture_dir() / "state.json"


def capture_status() -> str:
    path = _state_path()
    if not path.exists():
        return ENABLED
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ENABLED
    status = payload.get("status", ENABLED)
    if status not in {ENABLED, PAUSED, DISABLED}:
        return ENABLED
    return status


def set_capture_status(status: str) -> None:
    if status not in {ENABLED, PAUSED, DISABLED}:
        raise ValueError(status)
    _state_path().write_text(json.dumps({"status": status}, indent=2) + "\n", encoding="utf-8")


def capture_allowed() -> bool:
    return capture_status() == ENABLED


@dataclass(frozen=True)
class ApiSettings:
    base_url: str
    api_key: str

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)


def api_settings() -> ApiSettings:
    load_env()
    return ApiSettings(
        base_url=os.environ.get("MEMPLUG_API_URL", "").strip().rstrip("/"),
        api_key=os.environ.get("MEMPLUG_API_KEY", "").strip(),
    )
