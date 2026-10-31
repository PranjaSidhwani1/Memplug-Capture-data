"""Drop hidden reasoning, cap tool output, and mask obvious secrets."""

from __future__ import annotations

import json
import re
from pathlib import Path

_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|secret|token|password|authorization)\s*[:=]\s*\S+"
    r"|sk-[A-Za-z0-9]{10,}"
    r"|github_pat_[A-Za-z0-9_]+"
    r"|AKIA[0-9A-Z]{16}"
    r"|Bearer\s+[A-Za-z0-9\-._~+/]+=*"
)
_THINKING_TYPES = frozenset({"thinking", "redacted_thinking", "reasoning"})
_THINKING_KEYS = frozenset({"thinking", "redacted_thinking", "reasoning", "thought", "signature"})

MESSAGE_LIMIT = 32_000
TOOL_LIMIT = 8_000


def clean_path(value: str) -> str:
    """Cursor sometimes prefixes a Windows path with an extra slash."""
    if len(value) >= 4 and value[0] in "/\\" and value[2] == ":":
        return value[1:]
    return value


def project_name(path_value: str | None, fallback: str = "") -> str:
    raw = clean_path(path_value.strip()) if isinstance(path_value, str) else ""
    if not raw:
        raw = fallback.strip()
    if not raw:
        return ""
    return Path(raw).name or raw


def redact_text(value: str, limit: int) -> str:
    cleaned = _SECRET.sub("[redacted]", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "\n[truncated]"


def stringify(value: object, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return redact_text(value, limit)
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return redact_text(rendered, limit)


def text_from_content(content: object) -> str:
    """Visible text only. Thinking blocks are discarded."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type in _THINKING_TYPES or _THINKING_KEYS.intersection(block):
                continue
            if isinstance(block.get("text"), str) and block_type in {"text", "output_text", ""}:
                parts.append(block["text"])
        return "\n".join(part for part in parts if part.strip())
    if isinstance(content, dict):
        if str(content.get("type") or "") in _THINKING_TYPES:
            return ""
        if isinstance(content.get("text"), str):
            return content["text"]
    return ""
