#!/usr/bin/env python3
"""Copy freshly imported credentials into the HOMEs of runs that are still running.

A run stages credentials only when it starts, so a later login or import would otherwise
need a resume. Runs are found from the launch registry, from the running jobs' working
directories and from explicit paths; only runs whose Slurm job is running are updated.
"""

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile

from agent_cli import CREDENTIALS
from overlap import JOB_ID, query
import sessions


def registry(store):
    return Path(store).parent / "active-runs"


def register(store, run):
    # The launcher records each run that received credentials; stale entries are pruned on sync.
    directory = registry(store)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    run = Path(run).resolve()
    link = directory / hashlib.sha256(str(run).encode()).hexdigest()[:16]
    link.unlink(missing_ok=True)
    link.symlink_to(run, target_is_directory=True)


def running_jobs():
    """Return {job: working directory} for running jobs, or None when Slurm is unavailable."""
    try:
        output = query(["squeue", "--noheader", "--user", str(os.getuid()), "--states=RUNNING",
                        "--format=%A|%Z"])
    except (RuntimeError, OSError) as error:
        print(f"[WARN] running jobs are unknown ({error}); only --run paths are updated", file=sys.stderr)
        return None
    jobs = {}
    for line in output.splitlines():
        job, _, workdir = line.strip().partition("|")
        if JOB_ID.fullmatch(job):
            jobs[job] = workdir
    return jobs


def live(run):
    return (run / "home").is_dir() and not (run / "live/session_finished.txt").exists()


def job_of(run):
    try:
        return (run / "live/slurm_job_id.txt").read_text().strip()
    except OSError:
        return ""


def candidates(store, jobs, scan):
    found = []
    directory = registry(store)
    if directory.is_dir():
        for link in directory.iterdir():
            run = Path(os.path.realpath(link))
            if link.is_symlink() and live(run):
                found.append(run)
            else:
                link.unlink(missing_ok=True)
    roots = [Path(path) for path in scan] + [Path(path) for path in (jobs or {}).values() if path]
    for root in roots:
        found.extend(sessions.runs(root / ".agent-runs"))
    unique = {}
    for run in found:
        unique.setdefault(run.resolve(), None)
    return [run for run in unique if live(run) and jobs is not None and job_of(run) in jobs]


def write(home, relative, raw):
    # The run HOME is writable from the capsule; never follow its links out of it.
    target = home / relative
    root = home.resolve()
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    if parent.resolve() != root / relative.parent:
        raise ValueError(f"refusing a redirected credential path: {target}")
    if target.is_file() and not target.is_symlink() and target.read_bytes() == raw:
        return False
    with tempfile.NamedTemporaryFile(dir=parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            os.chmod(temporary, 0o600)
            stream.write(raw)
            stream.flush()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return True


def sync(store, agent, run):
    home = run / "home"
    homes = [("worker HOME", home)]
    reviewer = home / ".reviewer" / agent
    if reviewer.is_dir() and not reviewer.is_symlink():
        homes.append(("reviewer HOME", reviewer))
    updated = []
    for relative in map(Path, CREDENTIALS[agent]):
        source = Path(store) / agent / relative
        if not source.is_file():
            continue
        raw = source.read_bytes()
        for label, target in homes:
            if write(target, relative, raw) and label not in updated:
                updated.append(label)
    return updated


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--store", required=True)
    reg.add_argument("run")
    push = sub.add_parser("sync")
    push.add_argument("--store", required=True)
    push.add_argument("--agent", action="append", required=True, choices=sorted(CREDENTIALS))
    push.add_argument("--scan", action="append", default=[])
    push.add_argument("--run", action="append", default=[])
    args = parser.parse_args()
    if args.action == "register":
        register(args.store, args.run)
        return 0
    jobs = running_jobs()
    runs = candidates(args.store, jobs, args.scan)
    for path in args.run:
        run = Path(path).resolve()
        if not live(run):
            print(f"[SKIP] not a running session: {run}", file=sys.stderr)
        elif run not in runs:
            runs.append(run)
    if not runs:
        print("[auth sync] no running sessions to update")
    rc = 0
    for run in runs:
        for agent in args.agent:
            try:
                updated = sync(args.store, agent, run)
            except (OSError, ValueError) as error:
                print(f"[FAIL] {agent} -> {run}: {error}", file=sys.stderr)
                rc = 1
                continue
            if updated:
                print(f"[SYNCED] {agent} -> {run} ({', '.join(updated)})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
