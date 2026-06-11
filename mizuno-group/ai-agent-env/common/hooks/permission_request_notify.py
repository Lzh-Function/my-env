#!/usr/bin/env python3
"""Send a Slack notification for Claude Code PermissionRequest events."""

from __future__ import annotations

import json
import socket
import sys
import urllib.request


SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"


def format_detail(tool: str, inp: dict) -> str:
    if tool == "Bash":
        return "```" + inp.get("command", "?") + "```"
    if tool in ("Write", "Edit", "Read"):
        return "`" + inp.get("file_path", "?") + "`"
    if tool == "WebFetch":
        return "`" + inp.get("url", "?") + "`"
    if tool == "WebSearch":
        return "`" + inp.get("query", "?") + "`"
    return "\n".join(f"{k}: `{v}`" for k, v in inp.items())


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    hostname = socket.gethostname().split(".")[0]
    tool = payload.get("tool_name", "unknown")
    detail = format_detail(tool, payload.get("tool_input", {}))

    text = f"*[{hostname}] :bell: Permission Request — {tool}*\n{detail}"
    body = json.dumps({"text": text}).encode()

    try:
        req = urllib.request.Request(
            SLACK_WEBHOOK_URL,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
