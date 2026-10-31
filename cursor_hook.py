"""Cursor launches this file. Stdin is the hook payload.

Uses Python 3.13 (C:\\Python313\\python.exe) because Anaconda's SSL stack
breaks MongoDB Atlas TLS on this machine.
"""

import os
import sys

os.environ["MEMPLUG_ENV_FILE"] = r"d:\MemoPlug\capture\.env"
sys.path.insert(0, r"d:\MemoPlug\capture\src")

from memplug_capture.hook import run_hook

raise SystemExit(run_hook("cursor"))
