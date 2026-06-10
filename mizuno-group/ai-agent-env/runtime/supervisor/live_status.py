"""Live status helpers for agent run directories."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_status(run_dir: Path, status: str, **extra: object) -> None:
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "updated_at": utc_now(), **extra}
    (live_dir / "status.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (live_dir / "heartbeat.txt").write_text(utc_now() + "\n", encoding="utf-8")
    append_event(run_dir, "status", {"status": status, **extra})


def write_current_task(run_dir: Path, task: str) -> None:
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    (live_dir / "current_task.md").write_text(task.rstrip() + "\n", encoding="utf-8")
    append_event(run_dir, "current_task", {"task": task})


def append_event(run_dir: Path, event: str, payload: dict[str, object] | None = None) -> None:
    live_dir = run_dir / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    record = {"ts": utc_now(), "event": event, "payload": payload or {}}
    with (live_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
