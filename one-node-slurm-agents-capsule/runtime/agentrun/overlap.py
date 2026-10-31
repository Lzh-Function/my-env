#!/usr/bin/env python3
"""List the user's running Slurm jobs and describe one for an overlapping step."""

import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from history import slurm_query
import sessions


JOB_ID = re.compile(r"[0-9]+")


def query(args):
    # Caller display filters must not hide or reshape jobs.
    env = {key: value for key, value in os.environ.items() if not key.startswith("SQUEUE_")}
    env["LC_ALL"] = "C"
    try:
        result = slurm_query(args, env=env, timeout=10)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"{args[0]} に問い合わせできません: {error}") from error
    if result.returncode:
        raise RuntimeError(f"{args[0]} が失敗しました: {result.stderr.strip()[:300]}")
    return result.stdout


def label(text):
    return " ".join(sessions.safe_text(text).split())


def agentrun_runs(parent):
    """Map job IDs to runs in this project; overlapping runs share one job."""
    found = {}
    for run in sessions.runs(parent):
        try:
            job = (run / "live/slurm_job_id.txt").read_text().strip()
        except OSError:
            continue
        if JOB_ID.fullmatch(job):
            found.setdefault(job, []).append(run.name)
    return found


def jobs(parent):
    if not shutil.which("squeue"):
        return
    try:
        # The job name is last because it may contain the separator.
        output = query(["squeue", "--noheader", "--user", str(os.getuid()), "--states=RUNNING",
                        "--format=%A|%P|%N|%C|%M|%l|%b|%j"])
    except RuntimeError as error:
        print(f"overlap: 実行中のジョブを確認できません（{label(str(error))}）", file=sys.stderr)
        return
    runs = agentrun_runs(parent)
    for line in output.splitlines():
        fields = [field.strip() for field in line.split("|", 7)]
        if len(fields) != 8 or not JOB_ID.fullmatch(fields[0]):
            continue
        job, partition, nodes, cpus, elapsed, limit, gres, name = map(label, fields)
        parts = [job, name or "-", f"partition={partition}", f"node={nodes}", f"CPU={cpus}"]
        if gres and gres != "N/A" and not re.search(r"gpu(?::[^:,]+)?:0$", gres):
            parts.append(f"gres={gres}")
        parts.append(f"経過={elapsed}/{limit}")
        if job in runs:
            names = runs[job]
            parts.append("agentrun=" + label(names[-1]) + (f" ほか{len(names) - 1}件" if len(names) > 1 else ""))
        print("  ".join(parts))


def gpu_count(record, field):
    for key in ("AllocTRES", "TRES"):
        tres = field(key)
        if tres:
            plain = re.search(r"(?:^|,)gres/gpu=(\d+)", tres)
            if plain:
                return int(plain[1])
            return sum(int(count) for count in re.findall(r"(?:^|,)gres/gpu:[^=,]+=(\d+)", tres))
    legacy = re.search(r"(?:^|\s)(?:TresPerNode|Gres)=(?:gres[:/])?gpu(?::[^:,\s]+)?:(\d+)", record)
    return int(legacy[1]) if legacy else 0


def info(job):
    if not JOB_ID.fullmatch(job):
        raise ValueError("overlap 先の Slurm job ID は数字で指定してください: " + label(job))
    try:
        output = query(["scontrol", "--oneliner", "show", "job", job])
    except RuntimeError as error:
        if "Invalid job id" not in str(error):
            raise
        output = ""
    record = output.splitlines()[0] if output.strip() else ""

    def field(key):
        match = re.search(rf"(?:^|\s){key}=(\S*)", record)
        return match[1] if match else ""

    if field("JobId") != job:
        raise ValueError(f"Slurm job {job} が見つかりません")
    user = re.fullmatch(r".*\((\d+)\)", field("UserId"))
    if not user or int(user[1]) != os.getuid():
        raise ValueError(f"Slurm job {job} は自分のジョブではありません")
    state = field("JobState")
    if state != "RUNNING":
        raise ValueError(f"Slurm job {job} は実行中ではありません（{state or '状態不明'}）")
    cpus = field("NumCPUs")
    if not JOB_ID.fullmatch(cpus) or int(cpus) < 1:
        raise ValueError(f"Slurm job {job} の CPU 数を取得できません")
    name = re.search(r"(?:^|\s)JobName=(.*?)\s+UserId=", record)
    for value in (job, cpus, str(gpu_count(record, field)), field("Partition"), field("NodeList"),
                  field("TimeLimit"), field("RunTime"), label(name[1]) if name else ""):
        print(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("jobs", "info"))
    parser.add_argument("target")
    args = parser.parse_args()
    if args.action == "jobs":
        jobs(Path(args.target))
    else:
        info(args.target)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print("overlap: " + label(str(error)), file=sys.stderr)
        sys.exit(2)
