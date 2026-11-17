#!/usr/bin/env python3
"""Read-only run listings for the wizard's tool menu (pick a run, show its summary and logs)."""

import argparse
import json
import os
import sys
from pathlib import Path

import sessions
from auth_sync import live, registry
from overlap import JOB_ID, query

LOG_FILES = ("slurm.out", "slurm.err", "stdout.log", "stderr.log", "events.jsonl", "command_log.jsonl",
             "history_export.log")


def running_jobs():
    """Running job IDs, or None when Slurm cannot be asked (then running state is unknown)."""
    try:
        output = query(["squeue", "--noheader", "--user", str(os.getuid()), "--states=RUNNING", "--format=%A"])
    except (RuntimeError, OSError):
        return None
    return {line.strip() for line in output.splitlines() if JOB_ID.fullmatch(line.strip())}


def first_line(path):
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
    except (OSError, UnicodeError):
        return ""
    return lines[0].strip() if lines else ""


def state(run, jobs):
    job = first_line(run / "live/slurm_job_id.txt")
    status = sessions.read_json(run / "live/status.json")
    status = status.get("status", "") if isinstance(status, dict) else ""
    if job and live(run):
        if jobs is None:
            return f"job {job}（実行状態は不明）"
        if job in jobs:
            return f"実行中 job {job}"
    if job or status in ("success", "failed", "cancelled", "timeout"):
        return "終了" + (f": {status}" if status else "")
    return "準備のみ"


def all_runs(parent):
    """Runs in this directory, then runs launched elsewhere that the launch registry knows about."""
    found = list(sessions.runs(parent))
    directory = registry(Path.home() / ".agentrun/auth")
    for link in sorted(directory.iterdir()) if directory.is_dir() else []:
        target = Path(os.path.realpath(link))
        if link.is_symlink() and target.is_dir():
            found.append(target)
    unique = {}
    for run in found:
        unique.setdefault(run.resolve(), None)
    return sorted(unique, key=lambda run: run.name, reverse=True)


def label(run, jobs, here):
    try:
        data = sessions.manifest(run)
        agent, mode = data["agent"], data["mode"]
    except (ValueError, OSError, KeyError, TypeError):
        agent, mode = "?", "?"
    title = first_line(run / "artifacts/run_title.txt")
    where = "" if run.parent == here else f"  ({run.parent.parent.name})"
    text = f"{run.name}  {agent} {mode}  [{state(run, jobs)}]{where}" + (f"  {title}" if title else "")
    return sessions.safe_text(text).replace("\n", " ")


def summary(run):
    jobs = running_jobs()
    data = sessions.manifest(run)
    lines = [f"run: {run.name}", f"場所: {run}", f"agent / mode: {data['agent']} / {data['mode']}",
             f"作業リポジトリ: {data['repo']}", f"状態: {state(run, jobs)}"]
    for title, path in (("タイトル", "artifacts/run_title.txt"), ("作業中", "live/current_task.md")):
        text = first_line(run / path)
        if text and text != "initialized":
            lines.append(f"{title}: {text}")
    export = sessions.read_json(run / "live/history_export.json")
    if isinstance(export, dict) and export.get("status"):
        lines.append(f"会話履歴の保存: {export['status']}")
    reviews = [path for path in (run / "reviews").glob("**/state.json")] if (run / "reviews").is_dir() else []
    if reviews:
        lines.append(f"相互監査: {len(reviews)} 件")
    return "\n".join(sessions.safe_text(line) for line in lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("runs", "summary", "logs", "has-reviews", "batch", "resumable"))
    parser.add_argument("path", type=Path)
    options = parser.parse_args()
    path = options.path.resolve()
    if options.action == "runs":
        jobs = running_jobs()
        for run in all_runs(path / ".agent-runs"):
            print(f"{run}\t{label(run, jobs, path / '.agent-runs')}")
    elif options.action == "summary":
        print(summary(path))
    elif options.action == "logs":
        for name in LOG_FILES:
            file = path / "live" / name
            if file.is_file() and file.stat().st_size:
                print(f"{name}\t{file.stat().st_size:,} bytes")
    elif options.action == "has-reviews":
        return 0 if (path / "reviews").is_dir() and any((path / "reviews").glob("**/state.json")) else 1
    elif options.action == "resumable":
        # A saved conversation exists and the session is not running any more.
        _data, session, _label = sessions.describe(path)
        return 0 if session and not live(path) else 1
    elif options.action == "batch":
        # A batch run was submitted with sbatch and has a job ID to collect history for.
        return 0 if (path / "submit.sbatch").is_file() and JOB_ID.fullmatch(first_line(path / "live/slurm_job_id.txt")) else 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        print("run_menu: " + sessions.safe_text(str(error)), file=sys.stderr)
        sys.exit(2)
