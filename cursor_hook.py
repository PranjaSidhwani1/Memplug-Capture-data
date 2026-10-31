"""Cursor launches this file. Stdin is the hook payload."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ.setdefault("MEMPLUG_ENV_FILE", str(ROOT / ".env"))
sys.path.insert(0, str(ROOT / "src"))

from memplug_capture.hook import run_hook

raise SystemExit(run_hook("cursor"))
