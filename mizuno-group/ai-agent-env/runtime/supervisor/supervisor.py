"""Minimal deterministic supervisor entry points.

This module intentionally contains only reusable primitives for now. Process
launching is wired after dry-run, image build, and Slurm smoke tests are
approved for the target cluster environment.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .live_status import append_event, write_current_task, write_status
from .report_collector import check_outputs, write_missing_artifact_placeholders


RUN_SUBDIRS = (
    "live",
    "artifacts",
    "reviews",
    "workspace",
    "scratch",
    "cache",
)


LIVE_FILES = (
    "stdout.log",
    "stderr.log",
    "command_log.jsonl",
    "events.jsonl",
    "slurm.out",
    "slurm.err",
    "exit_code.txt",
    "slurm_job_id.txt",
)


REVIEW_FILES = (
    "claude.md",
    "codex.md",
    "antigravity.md",
    "summary.md",
    "disagreements.json",
    "final_recommendation.md",
)


def initialize_run(run_dir: Path, mode: str, agent: str) -> None:
    for rel in RUN_SUBDIRS:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)
    for name in LIVE_FILES:
        (run_dir / "live" / name).touch(exist_ok=True)
    for name in REVIEW_FILES:
        path = run_dir / "reviews" / name
        if not path.exists():
            path.write_text("{}\n" if name.endswith(".json") else "", encoding="utf-8")
    write_missing_artifact_placeholders(run_dir)
    write_status(run_dir, "initialized", mode=mode, agent=agent)
    write_current_task(run_dir, "Run initialized.")


def finalize_run(run_dir: Path) -> bool:
    write_missing_artifact_placeholders(run_dir)
    checks = check_outputs(run_dir)
    success = all(check.exists for check in checks)
    write_status(run_dir, "success" if success else "failed", missing=[check.path for check in checks if not check.exists])
    return success


def disk_usage_bytes(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def run_supervised(command: list[str], run_dir: Path, *, walltime_seconds: int | None = None, max_disk_bytes: int | None = None) -> int:
    initialize_run(run_dir, mode="supervised", agent="unknown")
    write_current_task(run_dir, "Starting supervised process.")
    started = time.monotonic()
    stdout_path = run_dir / "live" / "stdout.log"
    stderr_path = run_dir / "live" / "stderr.log"

    with stdout_path.open("ab") as stdout, stderr_path.open("ab") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        while process.poll() is None:
            if walltime_seconds is not None and time.monotonic() - started > walltime_seconds:
                append_event(run_dir, "timeout", {"walltime_seconds": walltime_seconds})
                process.terminate()
                process.wait(timeout=30)
                write_status(run_dir, "timeout")
                return process.returncode or 124
            if max_disk_bytes is not None and disk_usage_bytes(run_dir) > max_disk_bytes:
                append_event(run_dir, "disk_budget_exceeded", {"max_disk_bytes": max_disk_bytes})
                process.terminate()
                process.wait(timeout=30)
                write_status(run_dir, "failed", reason="disk budget exceeded")
                return process.returncode or 122
            write_status(run_dir, "running", pid=process.pid)
            time.sleep(5)

    append_event(run_dir, "process_exit", {"returncode": process.returncode})
    (run_dir / "live" / "exit_code.txt").write_text(f"{process.returncode}\n", encoding="utf-8")
    finalize_run(run_dir)
    return process.returncode
