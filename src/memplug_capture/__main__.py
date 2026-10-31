"""memplug-capture hook|status|enable|pause|disable"""

from __future__ import annotations

import argparse
import json
import sys

from memplug_capture.config import api_settings, capture_status, set_capture_status
from memplug_capture.drain import drain
from memplug_capture.hook import run_hook


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="memplug-capture")
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook")
    hook.add_argument("--source", required=True, choices=["claude_code", "codex", "cursor"])

    sub.add_parser("status")
    sub.add_parser("enable")
    sub.add_parser("pause")
    sub.add_parser("disable")

    args = parser.parse_args(argv)
    if args.command == "hook":
        sys.exit(run_hook(args.source))
    if args.command == "status":
        settings = api_settings()
        print(
            json.dumps(
                {
                    "status": capture_status(),
                    "api_url": settings.base_url or None,
                    "api_configured": settings.configured,
                    **drain(),
                }
            )
        )
        return
    if args.command == "enable":
        set_capture_status("enabled")
    elif args.command == "pause":
        set_capture_status("paused")
    elif args.command == "disable":
        set_capture_status("disabled")
    print(json.dumps({"status": capture_status()}))


if __name__ == "__main__":
    main()
