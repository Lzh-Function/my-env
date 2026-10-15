#!/usr/bin/env python3
"""Append a command event and update live status for an agent run."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_fields(raw: str) -> dict:
    """Pick only the tool name and command from a hook payload.

    The full payload is not logged: PostToolUse payloads carry the tool's output
    (e.g. the result of `env`), which could copy secret values into /runs.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"command": raw.strip()}
    if not isinstance(payload, dict):
        return {}
    if "toolCall" in payload:
        call = payload["toolCall"]
        return {"tool": call.get("name", ""), "command": call.get("args", {}).get("CommandLine", "")}
    command = payload.get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        command = " ".join(map(str, command))
    return {"tool": payload.get("tool_name", ""), "command": command}


def main() -> int:
    run_dir = Path(os.environ.get("AGENTRUN_DIR", "/runs"))
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)

    raw = sys.stdin.read()
    event = {
        "ts": utc_now(),
        "event": "command",
        **command_fields(raw),
    }

    with (live_dir / "command_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    status = {
        "status": "running",
        "updated_at": utc_now(),
        "last_event": "command",
    }
    (live_dir / "status.json").write_text(
        json.dumps(status, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (live_dir / "heartbeat.txt").write_text(utc_now() + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

