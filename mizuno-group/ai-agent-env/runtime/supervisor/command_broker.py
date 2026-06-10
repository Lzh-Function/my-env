"""Command broker primitives for supervised agent execution."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .policy import check_command


@dataclass(frozen=True)
class CommandEvent:
    ts: str
    command: str
    allowed: bool
    reason: str


def evaluate_command(command: str) -> CommandEvent:
    decision = check_command(command)
    return CommandEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        command=command,
        allowed=decision.allowed,
        reason=decision.reason,
    )


def append_command_event(run_dir: Path, event: CommandEvent) -> None:
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    with (live_dir / "command_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
