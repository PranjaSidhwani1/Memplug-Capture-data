"""memplug-capture hook|drain|enable|pause|disable|status"""

from __future__ import annotations

import argparse
import json
import sys

from memplug_capture.config import capture_status, mongo_settings, set_capture_status
from memplug_capture.drain import drain
from memplug_capture.hook import run_hook
from memplug_capture.store import counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="memplug-capture")
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook")
    hook.add_argument("--source", required=True, choices=["claude_code", "codex", "cursor"])

    sub.add_parser("drain")
    sub.add_parser("enable")
    sub.add_parser("pause")
    sub.add_parser("disable")
    sub.add_parser("status")

    args = parser.parse_args(argv)
    if args.command == "hook":
        sys.exit(run_hook(args.source))
    if args.command == "drain":
        print(json.dumps(drain()))
        return
    if args.command == "enable":
        set_capture_status("enabled")
    elif args.command == "pause":
        set_capture_status("paused")
    elif args.command == "disable":
        set_capture_status("disabled")
    _, database = mongo_settings()
    print(json.dumps({"status": capture_status(), "database": database, **counts()}))


if __name__ == "__main__":
    main()
