#!/usr/bin/env python3
"""Archive conversations on the launcher host, including detached batch jobs."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

import sessions
from history_export import archive_key, atomic_text, export_run, history_root, json_text


def archive(run):
    data = sessions.manifest(run)
    return export_run(run, data, sessions.state_dir(run, data))


def control_path(parent, run_id):
    if not sessions.NATIVE_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID for history collection")
    directory = history_root() / "jobs"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / (archive_key(parent, run_id) + ".json")


def find_run(parent, run_id):
    # Batch completion can append a title to the directory name.
    return sessions.resolve(parent, run_id)


def query_active(job_ref):
    job, _, cluster = job_ref.partition(";")
    if not re.fullmatch(r"[0-9]+", job) or (cluster and not re.fullmatch(r"[A-Za-z0-9_.-]+", cluster)):
        raise ValueError("Invalid Slurm job ID")
    args = ["squeue", "--noheader", "--jobs", job, "--format=%i"]
    if cluster:
        args += ["--clusters", cluster]
    env = {key: value for key, value in os.environ.items() if not key.startswith("SQUEUE_")}
    env["LC_ALL"] = "C"
    result = subprocess.run(args, capture_output=True, text=True, timeout=20, env=env)
    if result.returncode:
        # Some Slurm versions reject an ID once it leaves squeue. Accounting
        # may still confirm completion; a failed query alone is never enough.
        if shutil.which("sacct"):
            accounting = ["sacct", "--noheader", "--parsable2", "--jobs", job, "--format=JobIDRaw,State"]
            if cluster:
                accounting += ["--clusters", cluster]
            result2 = subprocess.run(accounting, capture_output=True, text=True, timeout=20)
            terminal = {"COMPLETED", "FAILED", "CANCELLED", "TIMEOUT", "OUT_OF_MEMORY",
                        "NODE_FAIL", "BOOT_FAIL", "DEADLINE", "PREEMPTED", "REVOKED"}
            if result2.returncode == 0:
                for line in result2.stdout.splitlines():
                    fields = line.split("|")
                    if len(fields) >= 2 and fields[0] == job and fields[1].strip() and fields[1].split()[0].rstrip("+") in terminal:
                        return False
        raise RuntimeError("squeue failed; job completion has not been established")
    return bool(result.stdout.strip())


def watch(parent, run_id, poll_interval=5):
    control = control_path(parent, run_id)
    info = json.loads(control.read_text())
    if info["origin_host"] != socket.gethostname():
        raise ValueError("Run the history collector on its original submission host: " + info["origin_host"])
    if info.get("status") == "archived":
        return
    # Serialize collectors without holding a SQLite transaction while waiting.
    with control.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        empty_queries = 0
        while True:
            try:
                active = query_active(info["job_ref"])
                empty_queries = 0 if active else empty_queries + 1
                run = find_run(parent, run_id)
                # Two absent queue entries protect against transient registration
                # delays. A completion marker also confirms wrapper cleanup ran.
                if not active and (empty_queries >= 2 or (run / "live/session_finished.txt").is_file()):
                    break
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                empty_queries = 0
                print(str(error), file=sys.stderr, flush=True)
            time.sleep(poll_interval)
        try:
            status = archive(run)
        except Exception as error:
            info.update(status="failed", error=str(error))
            atomic_text(control, json_text(info) + "\n")
            atomic_text(run / "live/history_export.json", json_text({
                "status": "failed", "archive_host": socket.gethostname(), "error": str(error)}) + "\n")
            raise
        info.pop("error", None)
        info.update(status="archived", archive=status)
        atomic_text(control, json_text(info) + "\n")


def submit(run):
    """Keep sbatch asynchronous and detach only the host-side history collector."""
    if not shutil.which("squeue"):
        raise ValueError("squeue is required for host-side batch history collection")
    data = sessions.manifest(run)
    control = control_path(run.parent, data["run_id"])
    result = subprocess.run(["sbatch", "--parsable", "--nodes=1", "--ntasks=1", str(run / "submit.sbatch")],
                            capture_output=True, text=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="")
    if result.returncode:
        raise RuntimeError(f"sbatch failed (exit {result.returncode})")
    job_ref = result.stdout.strip()
    if not re.fullmatch(r"[0-9]+(?:;[A-Za-z0-9_.-]+)?", job_ref):
        raise ValueError("sbatch returned an unexpected job ID; check the queue before retrying")
    info = {"run_id": data["run_id"], "job_ref": job_ref, "origin_host": socket.gethostname(),
            "submitted_at": time.time(), "status": "watching"}
    atomic_text(control, json_text(info) + "\n")
    with control.with_suffix(".log").open("a") as log:
        try:
            # Resolve relative configuration once, before detaching the collector.
            child_env = dict(os.environ, AGENTRUN_HISTORY_DIR=str(history_root()))
            child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "watch",
                                      str(run.parent), data["run_id"]],
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                     start_new_session=True, close_fds=True, env=child_env)
        except OSError as error:
            info.update(status="collector_start_failed", error=str(error))
            atomic_text(control, json_text(info) + "\n")
            raise RuntimeError(f"Job {job_ref} was submitted, but its history collector could not start; "
                               f"run agentrun history --watch {run}") from error
    print(f"Submitted batch job {job_ref.split(';', 1)[0]}")
    print(f"Host history collector: pid={child.pid}, state={control}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "submit", "watch", "collect", "failure"))
    parser.add_argument("path", type=Path)
    parser.add_argument("run_id", nargs="?")
    args = parser.parse_args()
    os.umask(0o077)
    path = args.path.resolve()
    if args.action == "failure":
        atomic_text(path / "live/history_export.json", json_text({
            "status": "failed", "archive_host": socket.gethostname(),
            "error": args.run_id or "Conversation export failed"}) + "\n")
    elif args.action == "watch":
        if not args.run_id:
            raise ValueError("watch requires the original run ID")
        watch(path, args.run_id)
    elif args.action == "submit":
        submit(path)
    elif args.action == "collect":
        data = sessions.manifest(path)
        control = control_path(path.parent, data["run_id"])
        if not control.is_file():
            job_ref = (path / "live/slurm_job_id.txt").read_text().strip()
            if not re.fullmatch(r"[0-9]+", job_ref):
                raise ValueError("No submitted Slurm job ID is available for this run")
            atomic_text(control, json_text({"run_id": data["run_id"], "job_ref": job_ref,
                        "origin_host": socket.gethostname(), "status": "watching"}) + "\n")
        watch(path.parent, data["run_id"])
    else:
        try:
            print(json_text(archive(path)))
        except Exception as error:
            atomic_text(path / "live/history_export.json", json_text({
                "status": "failed", "archive_host": socket.gethostname(), "error": str(error)}) + "\n")
            raise


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error) as error:
        print("history: " + str(error), file=sys.stderr)
        sys.exit(2)
