#!/usr/bin/env python3
"""Have the agent keep /runs/live/session_log.md: one short Japanese line per turn, and more in long turns.

Stop: each time the agent finishes a turn, the stop is blocked once with a short instruction to
append "- <time> <what this turn did>". The time is filled in here, so the agent needs no command
to look it up. When the agent stops again after writing it (stop_hook_active), the stop goes
through; the log costs one short tool call per turn. Claude Code and Codex read
{"decision": "block", "reason": ...}; worker_hook.py translates it for Antigravity.

Mid-turn (PostToolUse in Claude Code and Codex, PreInvocation in Antigravity): a turn that runs
long (a /goal, a long experiment) would otherwise leave one line for hours of work. The check is
mechanical: the agent is told nothing unless INTERVAL minutes have passed since the later of the
log's last line and the start of the turn; then it is asked once for a progress line and keeps
working. Short turns end (and write their line) first, so they never see it.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN = Path(os.environ.get("AGENTRUN_DIR", "/runs"))
LOG = RUN / "live/session_log.md"
# The turn last asked for a line (Antigravity only, see stop).
ASKED = RUN / "live/.session_log_turn"
# {"anchor": when the mid-turn clock last started, "idle": the agent has stopped since}.
CLOCK = RUN / "live/.session_log_clock.json"
# Put there by agentrun when an interactive session starts: its first turn only answers the
# start prompt ("wait for the user's first instruction"), so it gets no line and no command.
WAITING = RUN / "live/.session_log_waiting"
MID_TURN = ("PostToolUse", "PreInvocation")


def interval() -> float:
    """Seconds of work in one turn before a progress line is asked for; 0 turns it off."""
    try:
        return max(0.0, float(os.environ.get("AGENTRUN_SESSION_LOG_INTERVAL", "20"))) * 60
    except ValueError:
        return 20 * 60


def local_now() -> str:
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(os.environ.get("AGENTRUN_TIMEZONE") or "Asia/Tokyo")
    except Exception:  # noqa: BLE001 - no tz database in the image: use Japan time
        zone = timezone(timedelta(hours=9))
    return datetime.now(zone).strftime("%Y-%m-%d %H:%M")


def read_clock() -> dict:
    try:
        clock = json.loads(CLOCK.read_text())
        return clock if isinstance(clock, dict) else {}
    except (OSError, ValueError):
        return {}


def write_clock(clock: dict) -> None:
    try:
        CLOCK.parent.mkdir(parents=True, exist_ok=True)
        temporary = CLOCK.with_name(CLOCK.name + f".{os.getpid()}")
        temporary.write_text(json.dumps(clock))
        temporary.replace(CLOCK)
    except OSError:
        pass  # the log is a convenience: never fail the agent's tool call over it


def progress(payload: dict) -> str | None:
    """The instruction for a progress line when this turn has run INTERVAL without one, else None."""
    limit = interval()
    if not limit or payload.get("agent_id"):
        return None  # turned off, or a Claude Code subagent (its parent keeps the log)
    now = time.time()
    clock = read_clock()
    if clock.get("idle") or not isinstance(clock.get("anchor"), (int, float)):
        write_clock({"anchor": now, "idle": False})  # a new turn (or the first): start counting
        return None
    try:
        last_line = LOG.stat().st_mtime
    except OSError:
        last_line = 0.0
    if now - max(clock["anchor"], last_line) < limit:
        return None
    write_clock({"anchor": now, "idle": False})  # asked once per interval, written or not
    return (f"This turn has been running for a while. Append one progress line to {LOG} with a single "
            f"shell command: `- {local_now()} （途中）<ここまでにしたこと（日本語で 40 字以内）>`. "
            "Then continue your work exactly where you were; do not mention this line to the user.")


def stop(payload: dict) -> str | None:
    clock = read_clock()
    if clock.get("idle") is not True:
        write_clock({**clock, "idle": True})  # the next tool call starts a new turn's clock
    if payload.get("stop_hook_active"):
        return None  # already continuing because of a Stop hook: let it stop now
    # agy's own Stop hooks (a /goal check, for example) can keep it working after it wrote the
    # line and stop it again in the same turn without continuationActive; worker_hook.py names
    # the turn so it is asked only once.
    turn = payload.get("turn_key")
    if turn:
        try:
            if ASKED.read_text() == turn:
                return None
        except OSError:
            pass
        ASKED.parent.mkdir(parents=True, exist_ok=True)
        ASKED.write_text(turn)
    try:
        WAITING.unlink()
        return None  # the reply to the start prompt: nothing was done yet
    except FileNotFoundError:
        pass
    # Told to end with no text, models still confirm the write or repeat their answer (a
    # final message seems required); a fixed one-character final message is what they follow.
    return (f"Before you stop, append one line to {LOG} with a single shell command: "
            f"`- {local_now()} <この返答でしたこと（日本語で 40 字以内）>`. "
            f"Your final message after that command must be exactly `.` (one period) and nothing else"
            f" - your answer above already reached the user.")


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        return 0
    event = payload.get("hook_event_name") or "Stop"
    if event in MID_TURN:
        reason = progress(payload)
        if reason:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": reason}},
                             ensure_ascii=False))
        return 0
    reason = stop(payload)
    if reason:
        print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
