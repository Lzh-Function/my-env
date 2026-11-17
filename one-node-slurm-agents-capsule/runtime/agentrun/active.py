#!/usr/bin/env python3
"""Show the agentrun sessions that are running now, grouped by the Slurm job they run in.

Read-only: nothing here changes runs, jobs or the launch registry.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

import run_settings
import sessions
from auth_sync import live, registry
from overlap import JOB_ID, label, query

FIELDS = ("job", "state", "partition", "nodes", "cpus", "elapsed", "limit", "tres", "workdir", "name")


def running_jobs():
    # The job name is last because it may contain the separator.
    output = query(["squeue", "--noheader", "--user", str(os.getuid()), "--states=RUNNING",
                    "--format=%A|%T|%P|%N|%C|%M|%l|%b|%Z|%j"])
    jobs = {}
    for line in output.splitlines():
        values = [value.strip() for value in line.split("|", len(FIELDS) - 1)]
        if len(values) == len(FIELDS) and JOB_ID.fullmatch(values[0]):
            jobs[values[0]] = dict(zip(FIELDS, values))
    return jobs


def candidate_runs(jobs, scan):
    """Runs from the launch registry, the given directories and each job's working directory."""
    found = []
    directory = registry(Path.home() / ".agentrun/auth")
    for link in sorted(directory.iterdir()) if directory.is_dir() else []:
        if link.is_symlink():
            found.append(Path(os.path.realpath(link)))
    for root in [*scan, *(Path(job["workdir"]) for job in jobs.values() if job["workdir"])]:
        found.extend(sessions.runs(root / ".agent-runs"))
    unique = {}
    for run in found:
        if run.is_dir():
            unique.setdefault(run.resolve(), None)
    return list(unique)


def job_of(run):
    try:
        return (run / "live/slurm_job_id.txt").read_text().strip()
    except OSError:
        return ""


def ago(seconds):
    if seconds < 60:
        return f"{int(seconds)}秒前"
    if seconds < 3600:
        return f"{int(seconds // 60)}分前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}時間前"
    return f"{int(seconds // 86400)}日前"


def describe(run, now):
    manifest = sessions.manifest(run)
    try:
        overlap_job = run_settings.load(run).get("overlap_job", "")
    except (ValueError, OSError, UnicodeError):
        overlap_job = ""
    updates = [path.stat().st_mtime for path in (run / "live").iterdir() if path.is_file()]
    try:
        task = (run / "live/current_task.md").read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError, UnicodeError):
        task = ""
    return {
        "run": run, "agent": manifest["agent"], "mode": manifest["mode"], "repo": manifest["repo"],
        "overlap": bool(overlap_job), "updated": ago(now - max(updates)) if updates else "",
        "task": "" if task in ("", "initialized") else task,
    }


def text(value):
    """Terminal-safe single line that keeps the column spacing (label() would collapse it)."""
    return sessions.safe_text(value).replace("\n", " ")


def short_path(path):
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def show(jobs, runs, others):
    if not runs:
        print("実行中の agentrun はありません。")
    for job_id in sorted(runs, key=int):
        job = jobs[job_id]
        members = sorted(runs[job_id], key=lambda item: (item["overlap"], item["run"].name))
        # squeue %b prints the GPU request as gpu:8, gpu:a100:8 or gres/gpu:8 (N/A without GPUs).
        gpus = sum(int(n) for n in re.findall(r"gpu(?::[^:,]+)?:(\d+)", job["tres"]))
        resources = f"CPU={job['cpus']}" + (f" GPU={gpus}" if gpus else "")
        owner = "" if any(not item["overlap"] for item in members) else "（agentrun 以外で起動したジョブ）"
        print(text(f"job {job_id}  {job['name']}  partition={job['partition']}  node={job['nodes']}  "
                    f"{resources}  経過 {job['elapsed']}/{job['limit']}{owner}"))
        for index, item in enumerate(members):
            last = index == len(members) - 1
            kind = "overlap" if item["overlap"] else "ジョブ本体"
            print(text(f"{'└─' if last else '├─'} {item['run'].name}  {item['agent']} {item['mode']}  {kind}  "
                        f"repo={short_path(item['repo'])}" + (f"  最終更新 {item['updated']}" if item["updated"] else "")))
            details = [f"作業: {item['task']}"] if item["task"] else []
            details.append(short_path(str(item["run"])))
            for detail in details:
                print(("   " if last else "│  ") + "  " + text(detail))
    if others:
        print()
        print("agentrun が動いていない実行中ジョブ（--overlap の重ね先に使えます）:")
        for job_id in sorted(others, key=int):
            job = jobs[job_id]
            print(text(f"  job {job_id}  {job['name']}  partition={job['partition']}  node={job['nodes']}  "
                        f"CPU={job['cpus']}  経過 {job['elapsed']}/{job['limit']}"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scan", action="append", default=[], type=Path,
                        help="also look for runs in DIR/.agent-runs (the current directory is always included)")
    options = parser.parse_args()
    jobs = running_jobs()
    now = time.time()
    runs = {}
    for run in candidate_runs(jobs, [Path.cwd(), *options.scan]):
        job = job_of(run)
        # A finished session removes its home; a job that ended is no longer listed by squeue.
        if job not in jobs or not live(run):
            continue
        try:
            runs.setdefault(job, []).append(describe(run, now))
        except (ValueError, OSError, UnicodeError, KeyError) as error:
            print(f"ps: {run.name} を読めません: {label(str(error))}", file=sys.stderr)
    show(jobs, runs, [job for job in jobs if job not in runs])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as error:
        print("ps: " + label(str(error)), file=sys.stderr)
        sys.exit(2)
