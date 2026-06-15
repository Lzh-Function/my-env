#!/usr/bin/env python3
"""Send Slack notification on agent Stop, then clean up session temp files."""

from __future__ import annotations

import glob
import json
import socket
import sys
import urllib.request
from pathlib import Path


SLACK_WEBHOOK_URL = "SLACK_WEBHOOK_URL" # Set your Slack Incoming Webhook URL here


def detect_agent(payload: dict) -> str:
    if "conversationId" in payload:
        return "Antigravity"
    if "model" in payload or "turn_id" in payload:
        return "Codex"
    return "Claude Code"


def extract_summary(payload: dict, agent: str) -> str:
    if agent == "Antigravity":
        reason = payload.get("terminationReason", "")
        if reason and reason != "model_stop":
            return f"終了理由: {reason}"
        return "作業が完了しました。"
    # Claude Code and Codex both provide last_assistant_message
    msg = payload.get("last_assistant_message", "")
    if not msg:
        return "作業が完了しました。"
    msg = msg.replace("\n", " ").strip()
    return (msg[:120] + "...") if len(msg) > 120 else msg


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {}

    agent = detect_agent(payload)
    summary = extract_summary(payload, agent)
    hostname = socket.gethostname().split(".")[0]
    text = f"*[{hostname}] {agent} 完了* :white_check_mark:\n{summary}"
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

    for f in glob.glob("/tmp/claude_python_env_*"):
        Path(f).unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
