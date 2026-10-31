import json
import subprocess

command = (
    "python -c 'import os,sys;"
    'os.environ["MEMPLUG_API_URL"]="https://memplug-capture-data.onrender.com";'
    'os.environ["MEMPLUG_API_KEY"]="mpl_0O4Hcq5ACOL2CxIhFQ7MO9XPfDq2I2ELgODhbvHTpPE";'
    'sys.argv=["memplug-capture","hook","--source","cursor"];'
    "from memplug_capture.__main__ import main; main()'"
)
payload = json.dumps(
    {
        "hook_event_name": "afterAgentResponse",
        "conversation_id": "hook-check-ps",
        "text": "powershell reply",
        "workspace_roots": ["d:\\MemoPlug"],
    }
).encode()
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", command],
    input=payload,
    capture_output=True,
)
print("code", result.returncode)
print("stdout", result.stdout.decode("utf-8", "replace")[:500])
print("stderr", result.stderr.decode("utf-8", "replace")[:800])
