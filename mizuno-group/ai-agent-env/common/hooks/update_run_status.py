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


def main() -> int:
    run_dir = Path(os.environ.get("AGENTRUN_DIR", "/runs"))
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)

    raw = sys.stdin.read()
    event = {
        "ts": utc_now(),
        "event": "command",
        "payload": raw.strip(),
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

