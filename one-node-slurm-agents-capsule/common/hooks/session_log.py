#!/usr/bin/env python3
"""Stop hook: before the agent stops, have it append one short line to the session log.

Each time the agent finishes a turn, the stop is blocked once with a short instruction to
append "- <time> <what this turn did>" to /runs/live/session_log.md. The time is filled
in here, so the agent needs no command to look it up. When the agent stops again after
writing it (stop_hook_active), the stop goes through; the log costs one short tool call
per turn. Claude Code and Codex read {"decision": "block", "reason": ...}; worker_hook.py
translates it for Antigravity.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN = Path(os.environ.get("AGENTRUN_DIR", "/runs"))
LOG = RUN / "live/session_log.md"
# The turn last asked for a line (Antigravity only, see main).
ASKED = RUN / "live/.session_log_turn"


def local_now() -> str:
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(os.environ.get("AGENTRUN_TIMEZONE") or "Asia/Tokyo")
    except Exception:  # noqa: BLE001 - no tz database in the image: use Japan time
        zone = timezone(timedelta(hours=9))
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return 0  # already continuing because of a Stop hook: let it stop now
    # agy's own Stop hooks (a /goal check, for example) can keep it working after it wrote the
    # line and stop it again in the same turn without continuationActive; worker_hook.py names
    # the turn so it is asked only once.
    turn = payload.get("turn_key")
    if turn:
        try:
            if ASKED.read_text() == turn:
                return 0
        except OSError:
            pass
        ASKED.parent.mkdir(parents=True, exist_ok=True)
        ASKED.write_text(turn)
    line = f"- {local_now()} "
    reason = (f"agentrun: append exactly one line to {LOG} and stop without replying: "
              f"`{line}<what this turn did, max 15 words>`")
    print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
