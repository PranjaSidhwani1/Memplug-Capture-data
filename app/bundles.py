"""Hook files the console downloads. One native JSON per tool and OS."""

from __future__ import annotations

import re

TOOLS = ("cursor", "claude", "codex")
SYSTEMS = ("mac", "windows")

_SAFE = re.compile(r"[A-Za-z0-9_.:/@+-]+")

_FILENAMES = {
    ("cursor", "mac"): "memplug-cursor-macos.json",
    ("cursor", "windows"): "memplug-cursor-windows.json",
    ("claude", "mac"): "memplug-claude-macos.json",
    ("claude", "windows"): "memplug-claude-windows.json",
    ("codex", "mac"): "memplug-codex-macos.json",
    ("codex", "windows"): "memplug-codex-windows.json",
}

_PLACES = {
    ("cursor", "mac"): "~/.cursor/hooks.json",
    ("cursor", "windows"): "%USERPROFILE%\\.cursor\\hooks.json",
    ("claude", "mac"): "~/.claude/settings.json",
    ("claude", "windows"): "%USERPROFILE%\\.claude\\settings.json",
    ("codex", "mac"): "~/.codex/hooks.json",
    ("codex", "windows"): "%USERPROFILE%\\.codex\\hooks.json",
}


def filename(tool: str, system: str) -> str:
    return _FILENAMES[(tool, system)]


def destination(tool: str, system: str) -> str:
    return _PLACES[(tool, system)]


def build_bundle(tool: str, system: str, api_url: str, api_key: str) -> dict:
    if tool not in TOOLS or system not in SYSTEMS:
        raise ValueError("unknown bundle")
    command = _command(tool, system, api_url, api_key)
    if tool == "cursor":
        entry = {"command": command, "timeout": 15, "failClosed": False}
        return {
            "version": 1,
            "hooks": {
                "beforeSubmitPrompt": [entry],
                "afterAgentResponse": [dict(entry)],
            },
        }
    handler = {"type": "command", "command": command, "timeout": 15, "async": True}
    if system == "windows" and tool == "claude":
        handler["shell"] = "powershell"
    if system == "windows" and tool == "codex":
        handler["commandWindows"] = command
    group = {"hooks": [handler]}
    return {"hooks": {"UserPromptSubmit": [group], "Stop": [{"hooks": [dict(handler)]}]}}


def _command(tool: str, system: str, api_url: str, api_key: str) -> str:
    for label, value in (("API URL", api_url), ("API key", api_key)):
        if not _SAFE.fullmatch(value or ""):
            raise ValueError(f"{label} cannot be embedded in a hook command")
    source = {"cursor": "cursor", "claude": "claude_code", "codex": "codex"}[tool]
    if system == "windows" and tool == "codex":
        # Codex runs commandWindows through cmd. No quotes: the URL and key are a safe charset.
        return (
            f"set MEMPLUG_API_URL={api_url}&& "
            f"set MEMPLUG_API_KEY={api_key}&& "
            f"python -m memplug_capture hook --source {source}"
        )
    if system == "windows":
        # Cursor and Claude run this through PowerShell. Double quotes are stripped
        # before Python starts, and $input is empty because the JSON is on stdin.
        return (
            f"$env:MEMPLUG_API_URL='{api_url}'; "
            f"$env:MEMPLUG_API_KEY='{api_key}'; "
            f"python -m memplug_capture hook --source {source}"
        )
    code = (
        "import os,sys;"
        f'os.environ["MEMPLUG_API_URL"]="{api_url}";'
        f'os.environ["MEMPLUG_API_KEY"]="{api_key}";'
        f'sys.argv=["memplug-capture","hook","--source","{source}"];'
        "from memplug_capture.__main__ import main; main()"
    )
    return f"python3 -c '{code}'"
