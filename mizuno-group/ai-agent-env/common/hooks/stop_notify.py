#!/usr/bin/env python3
"""Send Slack notification on Claude Code Stop, then clean up session temp files."""

from __future__ import annotations

import glob
import json
import socket
import sys
import urllib.request
from pathlib import Path


SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/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"


def extract_summary(payload: dict) -> str:
    transcript = payload.get("transcript", [])
    assistant_msgs = [m for m in transcript if m.get("role") == "assistant"]
    if not assistant_msgs:
        return "作業が完了しました。"
    content = assistant_msgs[-1].get("content", "")
    if isinstance(content, list):
        text = " ".join(b.get("text", "") for b in content if b.get("type") == "text")
    elif isinstance(content, str):
        text = content
    else:
        text = ""
    text = text.replace("\n", " ").strip()
    if not text:
        return "作業が完了しました。"
    return (text[:120] + "...") if len(text) > 120 else text


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    summary = extract_summary(payload)
    hostname = socket.gethostname().split(".")[0]
    text = f"*[{hostname}] Claude Code 完了* :white_check_mark:\n{summary}"
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

    Path("/tmp/claude_allow_main_edit").unlink(missing_ok=True)
    for f in glob.glob("/tmp/claude_python_env_*"):
        Path(f).unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
