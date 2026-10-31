import json
import subprocess

command = r"C:\Python313\python.exe d:\MemoPlug\capture\cursor_hook.py"
cases = [
    ("user", {"hook_event_name": "beforeSubmitPrompt", "conversation_id": "hook-check-ps", "prompt": "user check", "workspace_roots": ["d:\\MemoPlug"]}),
    ("assistant", {"hook_event_name": "afterAgentResponse", "conversation_id": "hook-check-ps", "text": "assistant check", "workspace_roots": ["d:\\MemoPlug"]}),
]
for name, payload in cases:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        input=json.dumps(payload).encode(),
        capture_output=True,
    )
    print(name, "code", result.returncode)
    err = result.stderr.decode("utf-8", "replace").strip()
    out = result.stdout.decode("utf-8", "replace").strip()
    if out:
        print(" stdout", out[:300])
    if err:
        print(" stderr", err[:400])
