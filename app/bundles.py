"""Hook files the console downloads. One native JSON per tool and OS.

The command inside that JSON is the whole hook. It uses the Python standard
library only, so the editor does not need another file or an installed package.
"""

from __future__ import annotations

import base64
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
    blob = base64.b64encode(_script(api_url, api_key, source).encode()).decode()
    if system == "windows" and tool == "codex":
        # Codex runs commandWindows through cmd, where double quotes hold the program.
        return f'python -c "import base64; exec(base64.b64decode(\'{blob}\').decode())"'
    if system == "windows":
        # Cursor and Claude run this through PowerShell. A " inside the command is
        # removed before Python starts, so the program is single-quoted and base64.
        return f"python -c 'import base64; exec(base64.b64decode(''{blob}'').decode())'"
    return f"python3 -c 'import base64; exec(base64.b64decode(\"{blob}\").decode())'"


def _script(api_url: str, api_key: str, source: str) -> str:
    return "\n".join(
        [
            "import json,re,sys,urllib.request",
            f"URL={api_url!r}",
            f"KEY={api_key!r}",
            f"SOURCE={source!r}",
            "LIMIT=32000",
            'SECRET=re.compile(r"(?i)(?:api[_-]?key|secret|token|password|authorization)\\s*[:=]\\s*\\S+|sk-[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]+|AKIA[0-9A-Z]{16}|Bearer\\s+[A-Za-z0-9\\-._~+/]+=*")',
            "def clip(value):",
            "    if not isinstance(value,str):",
            "        return ''",
            "    cleaned=SECRET.sub('[redacted]',value).strip()",
            "    if len(cleaned)<=LIMIT:",
            "        return cleaned",
            "    return cleaned[:LIMIT]+'\\n[truncated]'",
            "def leaf(value):",
            "    if not isinstance(value,str):",
            "        return ''",
            "    raw=value.strip()",
            "    if len(raw)>=4 and raw[0] in '/\\\\' and raw[2]==':':",
            "        raw=raw[1:]",
            "    raw=raw.replace('\\\\','/').rstrip('/')",
            "    return raw.split('/')[-1] if raw else ''",
            "def project(payload):",
            "    roots=payload.get('workspace_roots')",
            "    if isinstance(roots,list):",
            "        for root in roots:",
            "            name=leaf(root)",
            "            if name:",
            "                return name",
            "    return leaf(payload.get('cwd'))",
            "raw=sys.stdin.buffer.read()",
            "if not raw.strip():",
            "    raise SystemExit(0)",
            "try:",
            "    payload=json.loads(raw.decode('utf-8'))",
            "except Exception:",
            "    raise SystemExit(0)",
            "if not isinstance(payload,dict):",
            "    raise SystemExit(0)",
            "name=str(payload.get('hook_event_name') or '').replace('_','').lower()",
            "if 'thought' in name:",
            "    raise SystemExit(0)",
            "session=str(payload.get('conversation_id') or payload.get('session_id') or '').strip()",
            "if not session:",
            "    raise SystemExit(0)",
            "role=''",
            "text=''",
            "if name in ('beforesubmitprompt','userpromptsubmit'):",
            "    role='user'",
            "    prompt=payload.get('prompt')",
            "    if not isinstance(prompt,str):",
            "        prompt=payload.get('userPrompt') if isinstance(payload.get('userPrompt'),str) else ''",
            "    text=clip(prompt)",
            "elif name in ('afteragentresponse','agentresponse','stop') and not payload.get('stop_hook_active'):",
            "    role='assistant'",
            "    text=clip(payload.get('text'))",
            "    if not text:",
            "        text=clip(payload.get('last_assistant_message'))",
            "if not role or not text:",
            "    raise SystemExit(0)",
            "body=json.dumps({'source':SOURCE,'session_id':session,'project':project(payload),'role':role,'content':text}).encode()",
            "request=urllib.request.Request(URL+'/v1/capture/message',data=body,headers={'Authorization':'Bearer '+KEY,'Content-Type':'application/json'},method='POST')",
            "try:",
            "    urllib.request.urlopen(request,timeout=8).read()",
            "except Exception:",
            "    pass",
            "",
        ]
    )
