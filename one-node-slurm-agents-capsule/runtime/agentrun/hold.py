#!/usr/bin/env python3
"""Hold a node with an idle Slurm job, and run agentrun sessions as steps inside it.

`agentrun hold start` submits a job that takes everything the partition's node offers (all
CPUs, all memory, all GPUs) and does nothing but wait. Interactive sessions then join it with
`srun --jobid --overlap`, so closing one session no longer ends the others. Batch runs are
queued in the hold job's folder; the job itself starts each one as a step, so they do not
depend on any process on the login host.

The hold job's folder (its working directory, shared with the compute node like the run
folders) holds hold.sbatch, hold.json, queue/ (batch runs waiting to start), started/ and
hold.out (the job's log).
"""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import sessions
from auth_sync import live, registry
from history import slurm_query

NAME = "agentrun-hold"
JOB_ID = re.compile(r"[0-9]+")
FIELDS = ("job", "state", "partition", "cpus", "tres", "limit", "left", "elapsed", "workdir")
ROOT = Path(__file__).resolve().parents[2]


def label(text):
    return " ".join(sessions.safe_text(str(text)).split())


def text(value):
    """Terminal-safe single line that keeps the column spacing (label() would collapse it)."""
    return sessions.safe_text(str(value)).replace("\n", " ")


def query(args, timeout=10):
    # Caller display filters must not hide or reshape jobs.
    env = {key: value for key, value in os.environ.items() if not key.startswith(("SQUEUE_", "SINFO_", "SBATCH_"))}
    env["LC_ALL"] = "C"
    try:
        result = slurm_query(args, env=env, timeout=timeout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"{args[0]} に問い合わせできません: {error}") from error
    if result.returncode:
        raise RuntimeError(f"{args[0]} が失敗しました: {result.stderr.strip()[:300]}")
    return result.stdout


def gpus_in(text):
    # squeue %b / sinfo %G print gpu:8, gpu:a100:8, gres/gpu:8 or gpu:a100:8(S:0-1); N/A without GPUs.
    return sum(int(n) for n in re.findall(r"gpu(?::[^:,(]+)?:(\d+)", text or ""))


def holders(states="RUNNING,PENDING"):
    """The user's hold jobs, oldest first."""
    if not shutil.which("squeue"):
        return []
    output = query(["squeue", "--noheader", "--user", str(os.getuid()), "--name", NAME, f"--states={states}",
                    "--format=%A|%T|%P|%C|%b|%l|%L|%M|%Z"])
    found = []
    for line in output.splitlines():
        values = [value.strip() for value in line.split("|", len(FIELDS) - 1)]
        if len(values) == len(FIELDS) and JOB_ID.fullmatch(values[0]):
            record = dict(zip(FIELDS, values))
            record["gpus"] = gpus_in(record["tres"])
            found.append(record)
    return sorted(found, key=lambda record: int(record["job"]))


def holder(job):
    for record in holders("RUNNING,PENDING,CONFIGURING,SUSPENDED"):
        if record["job"] == job:
            return record
    return None


def describe(record):
    gpus = f" / GPU {record['gpus']}" if record["gpus"] else ""
    if record["state"] == "RUNNING":
        when = f"経過 {record['elapsed']} / 上限 {record['limit']}（残り {record['left']}）"
    else:
        when = f"割り当て待ち（{record['state']}）/ 上限 {record['limit']}"
    return text(f"job {record['job']}  partition={record['partition']}  CPU {record['cpus']}{gpus}  {when}")


def default_partition():
    for line in query(["sinfo", "--noheader", "--format=%P"]).splitlines():
        if line.strip().endswith("*"):
            return line.strip().rstrip("*")
    return ""


def partition_resources(partition):
    """CPUs, memory (MB), GPUs and time limit of the partition's largest node."""
    args = ["sinfo", "--noheader", "--Node", "--format=%N|%c|%m|%G"]
    if partition:
        args[1:1] = ["--partition", partition]
    best = None
    for line in query(args).splitlines():
        values = [value.strip() for value in line.split("|")]
        if len(values) != 4 or not values[1].isdigit():
            continue
        node = (int(values[1]), int(values[2]) if values[2].isdigit() else 0, gpus_in(values[3]), values[0])
        best = node if best is None or node[:3] > best[:3] else best
    if best is None:
        raise ValueError(f"パーティション {partition or '（既定）'} のノードが見つかりません")
    limit_args = ["sinfo", "--noheader", "--format=%l"] + (["--partition", partition] if partition else [])
    limits = [line.strip() for line in query(limit_args).splitlines() if line.strip()]
    return {"cpus": best[0], "mem": best[1], "gpus": best[2], "node": best[3], "limit": limits[0] if limits else ""}


def hold_base():
    configured = os.environ.get("AGENTRUN_HOLD_DIR")
    # The folder must be visible from the compute node; run folders already are.
    return Path(configured).expanduser() if configured else Path.cwd() / ".agent-runs" / ".hold"


def script(folder, partition, resources, time_limit):
    lines = ["#!/usr/bin/env bash", f"#SBATCH --job-name={NAME}"]
    if partition:
        lines.append(f"#SBATCH --partition={partition}")
    lines += ["#SBATCH --nodes=1", "#SBATCH --ntasks=1", f"#SBATCH --cpus-per-task={resources['cpus']}",
              "#SBATCH --mem=0", "#SBATCH --exclusive"]
    if resources["gpus"]:
        lines.append(f"#SBATCH --gres=gpu:{resources['gpus']}")
    if time_limit:
        lines.append(f"#SBATCH --time={time_limit}")
    # The log path goes on sbatch's command line: #SBATCH lines cannot hold quotes or spaces.
    lines += ["",
              "# Holds the node and starts queued batch runs as steps; agentrun hold stop ends it.",
              f"exec python3 {sh_quote(str(Path(__file__).resolve()))} dispatch {sh_quote(str(folder))}", ""]
    return "\n".join(lines)


def sh_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def start(partition, time_limit, wait=True):
    partition = partition or os.environ.get("AGENTRUN_SLURM_PARTITION", "") or default_partition()
    for record in holders():
        if record["partition"] == partition:
            raise ValueError(f"パーティション {partition} には確保ジョブがあります: {describe(record)}"
                             "（agentrun hold status で確認、hold stop で解放できます）")
    resources = partition_resources(partition)
    if not time_limit and resources["limit"] not in ("", "infinite", "UNLIMITED"):
        time_limit = resources["limit"]
    folder = hold_base() / datetime.now().strftime("%Y%m%d_%H%M%S")
    for sub in ("queue", "started"):
        (folder / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
    (folder / "hold.sbatch").write_text(script(folder, partition, resources, time_limit))
    result = query(["sbatch", "--parsable", f"--chdir={folder}", f"--output={folder}/hold.out",
                    f"--error={folder}/hold.out", str(folder / "hold.sbatch")], timeout=30)
    job = result.strip().split(";", 1)[0]
    if not JOB_ID.fullmatch(job):
        raise ValueError("sbatch が想定外の job ID を返しました。squeue で確認してください")
    (folder / "hold.json").write_text(json.dumps({
        "job": job, "partition": partition, "cpus": resources["cpus"], "mem_mb": resources["mem"],
        "gpus": resources["gpus"], "node": resources["node"], "time": time_limit or "（上限なし）",
        "submitted_at": time.time()}, ensure_ascii=False, indent=1) + "\n")
    gpus = f"、GPU {resources['gpus']}" if resources["gpus"] else ""
    print(f"確保ジョブを投入しました: job {job}（partition={partition or '既定'}、CPU {resources['cpus']}、"
          f"メモリ全部{gpus}、制限時間 {time_limit or '上限なし'}）")
    print(f"確保ジョブのフォルダ: {folder}")
    return wait_running(job) if wait else True


def wait_running(job, timeout=None):
    """Wait until the hold job runs; Ctrl+C stops waiting but leaves the job queued."""
    began, shown = time.monotonic(), ""
    try:
        while True:
            record = holder(job)
            if record is None:
                raise ValueError(f"確保ジョブ {job} が見つかりません（終了したか、取り消されました）")
            if record["state"] == "RUNNING":
                print(f"確保ジョブ {job} が動き始めました。agentrun assist などは、この中で起動します。")
                return True
            if record["state"] != shown:
                print(f"確保ジョブ {job} の割り当てを待っています（{record['state']}）。Ctrl+C で待つのをやめられます"
                      "（ジョブは待ち行列に残ります）", flush=True)
                shown = record["state"]
            if timeout is not None and time.monotonic() - began > timeout:
                return False
            time.sleep(2)
    except KeyboardInterrupt:
        print(f"\n待つのをやめました。確保ジョブ {job} は待ち行列に残っています（agentrun hold status で確認）")
        return False


def print_fields(record):
    for key in ("job", "state", "partition", "cpus", "gpus", "limit", "left", "workdir"):
        print(record[key])


def select(partition="", need_running=True):
    """The hold job a launch should use: exit 0 and its fields, 3 none, 4 several, 5 only waiting ones.

    On a one-node cluster a hold job takes the node whatever the partition, so a single hold
    job is used for every launch; the partition only chooses between several.
    """
    records = holders()
    running = [record for record in records if record["state"] == "RUNNING"]
    usable = running if need_running else records
    if len(usable) > 1 and partition:
        usable = [record for record in usable if record["partition"] == partition] or usable
    if len(usable) == 1:
        print_fields(usable[0])
        return 0
    if len(usable) > 1:
        for record in usable:
            print(describe(record), file=sys.stderr)
        return 4
    if records:
        for record in records:
            print(describe(record), file=sys.stderr)
        return 5
    return 3


def is_holder(job):
    return holder(job) is not None


def enqueue(job, run):
    """Queue a prepared batch run; the hold job starts it as a step."""
    record = holder(job)
    if record is None:
        raise ValueError(f"job {job} は確保ジョブではありません（agentrun hold status で確認できます）")
    folder = Path(record["workdir"])
    queue = folder / "queue"
    if not queue.is_dir():
        raise ValueError(f"確保ジョブ {job} のフォルダが見つかりません: {folder}")
    run = run.resolve()
    item = queue / f"{run.name}.json"
    temporary = queue / f".{run.name}.json.tmp"
    temporary.write_text(json.dumps({"run": str(run), "queued_at": time.time()}) + "\n")
    temporary.replace(item)
    (run / "live/hold_job.txt").write_text(job + "\n")
    print(f"確保ジョブ {job} に投入しました。空きを待たずに、ジョブの中ですぐ始まります"
          + ("" if record["state"] == "RUNNING" else f"（確保ジョブが動き始めたら始まります: {record['state']}）"))


def dispatch(folder):
    """Inside the hold job: start each queued run as a step, until the job ends."""
    queue, started = folder / "queue", folder / "started"
    children = []
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    cpus = os.environ.get("SLURM_CPUS_PER_TASK") or os.environ.get("SLURM_CPUS_ON_NODE") or "1"
    print(f"{datetime.now().isoformat(timespec='seconds')} 確保ジョブ {os.environ.get('SLURM_JOB_ID', '')} を開始しました"
          f"（{os.environ.get('SLURMD_NODENAME', '')}、CPU {cpus}）", flush=True)
    while not stopping:
        for item in sorted(queue.glob("*.json")):
            try:
                run = Path(json.loads(item.read_text())["run"])
                item.replace(started / item.name)
            except (OSError, ValueError, KeyError) as error:
                print(f"投入を読めませんでした: {item.name}: {error}", flush=True)
                continue
            if not (run / "submit.sbatch").is_file():
                print(f"run が見つかりません: {run}", flush=True)
                continue
            command = ["srun", "--overlap", "--nodes=1", "--ntasks=1", f"--cpus-per-task={cpus}",
                       f"--job-name=agentrun-{run.name}"[:120],
                       f"--output={run}/live/slurm.out", f"--error={run}/live/slurm.err",
                       "bash", str(run / "submit.sbatch")]
            children.append((subprocess.Popen(command, stdin=subprocess.DEVNULL), run.name))
            print(f"{datetime.now().isoformat(timespec='seconds')} 開始: {run.name}", flush=True)
        for process, name in list(children):
            if process.poll() is not None:
                children.remove((process, name))
                print(f"{datetime.now().isoformat(timespec='seconds')} 終了: {name}（exit={process.returncode}）", flush=True)
        time.sleep(2)
    for process, _ in children:
        process.terminate()


def runs_on(job):
    """Sessions that run (or wait to run) in this job: the launch registry and this folder's runs."""
    found = {}
    directory = registry(Path.home() / ".agentrun/auth")
    candidates = [Path(os.path.realpath(link)) for link in sorted(directory.iterdir())] if directory.is_dir() else []
    candidates += sessions.runs(Path.cwd() / ".agent-runs")
    for run in candidates:
        if not run.is_dir() or run.resolve() in found or not live(run):
            continue
        ids = {read(run / "live/slurm_job_id.txt"), read(run / "live/hold_job.txt")}
        if job in ids:
            found[run.resolve()] = run
    return list(found.values())


def read(path):
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def session_line(run, record):
    manifest = sessions.manifest(run)
    step = read(run / "live/slurm_step_id.txt")
    queued = record and (Path(record["workdir"]) / "queue" / f"{run.name}.json").is_file()
    kind = "バッチ" if read(run / "live/hold_job.txt") else "対話"
    where = "開始待ち" if queued else (f"step {step}" if step else "起動中")
    return text(f"{run.name}  {manifest['agent']} {manifest['mode']}  {kind}  {where}  repo={manifest['repo']}")


def status():
    records = holders("RUNNING,PENDING,CONFIGURING,SUSPENDED")
    if not records:
        print("確保ジョブはありません（agentrun hold start で作れます）。")
        return
    for record in records:
        print(describe(record))
        print(text(f"  フォルダ: {record['workdir']}"))
        members = runs_on(record["job"])
        if not members:
            print("  載っているセッション: なし")
        for run in members:
            try:
                print("  - " + session_line(run, record))
            except (ValueError, OSError, KeyError):
                print("  - " + label(run.name))


def finish_without_start(run, reason):
    """Mark a batch run that never started, so its history collector and listings move on."""
    (run / "live/status.json").write_text(json.dumps({"status": "cancelled", "reason": reason}, ensure_ascii=False) + "\n")
    (run / "live/session_finished.txt").write_text(datetime.now().isoformat(timespec="seconds") + "\n")
    shutil.rmtree(run / "home", ignore_errors=True)


def cancel(run):
    run = run.resolve()
    if not live(run):
        print(f"{run.name} は動いていません。")
        return
    job = read(run / "live/slurm_job_id.txt") or read(run / "live/hold_job.txt")
    record = holder(job) if job else None
    if record:
        item = Path(record["workdir"]) / "queue" / f"{run.name}.json"
        try:
            item.unlink()
            finish_without_start(run, "開始前に取り消しました")
            print(f"{run.name} を開始前に取り消しました。")
            return
        except FileNotFoundError:
            pass
    step = read(run / "live/slurm_step_id.txt")
    if not (JOB_ID.fullmatch(job or "") and JOB_ID.fullmatch(step)):
        raise ValueError(f"{run.name} の Slurm ステップがわかりません（まだ起動中か、確保ジョブの外で動いています）")
    query(["scancel", f"{job}.{step}"])
    print(f"{run.name}（job {job} の step {step}）を止めました。確保ジョブとほかのセッションはそのままです。")


def stop(job, yes):
    records = holders("RUNNING,PENDING,CONFIGURING,SUSPENDED")
    if not job:
        if len(records) != 1:
            for record in records:
                print(describe(record))
            raise ValueError("確保ジョブがありません" if not records else "どの確保ジョブを解放するか job ID で指定してください")
        job = records[0]["job"]
    record = next((item for item in records if item["job"] == job), None)
    if record is None:
        raise ValueError(f"job {job} は確保ジョブではありません")
    members = runs_on(job)
    print(describe(record))
    for run in members:
        try:
            print("  - " + session_line(run, record))
        except (ValueError, OSError, KeyError):
            print("  - " + label(run.name))
    if members and not yes:
        if not sys.stdin.isatty():
            raise ValueError(f"載っているセッションが {len(members)} 件あります。止めてよければ --yes を付けてください")
        answer = input(f"載っているセッション {len(members)} 件も終了します。解放しますか？ [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("解放しませんでした。")
            return
    query(["scancel", job])
    for run in members:
        item = Path(record["workdir"]) / "queue" / f"{run.name}.json"
        if item.is_file():
            item.unlink(missing_ok=True)
            finish_without_start(run, "確保ジョブを解放したため開始しませんでした")
    print(f"確保ジョブ {job} を解放しました。")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("start")
    p.add_argument("--partition", default="")
    p.add_argument("--time", default="")
    p.add_argument("--no-wait", action="store_true")
    sub.add_parser("status")
    sub.add_parser("list")
    p = sub.add_parser("stop")
    p.add_argument("job", nargs="?", default="")
    p.add_argument("--yes", action="store_true")
    p = sub.add_parser("cancel")
    p.add_argument("run", type=Path)
    p = sub.add_parser("select")
    p.add_argument("--partition", default="")
    p.add_argument("--any", action="store_true", help="a hold job still waiting for its node also counts")
    p = sub.add_parser("is-holder")
    p.add_argument("job")
    p = sub.add_parser("info")
    p.add_argument("job")
    p = sub.add_parser("enqueue")
    p.add_argument("job")
    p.add_argument("run", type=Path)
    p = sub.add_parser("wait")
    p.add_argument("job")
    p = sub.add_parser("dispatch")
    p.add_argument("folder", type=Path)
    p = sub.add_parser("partition")
    p.add_argument("--partition", default="")
    args = parser.parse_args()
    if args.action == "start":
        # Exit 1: submitted, but not running yet (waiting was stopped).
        return 0 if start(args.partition, args.time, wait=not args.no_wait) else 1
    elif args.action == "status":
        status()
    elif args.action == "list":
        for record in holders():
            print(f"{record['job']}\t{record['state']}\t{describe(record)}")
    elif args.action == "stop":
        stop(args.job, args.yes)
    elif args.action == "cancel":
        cancel(args.run)
    elif args.action == "select":
        return select(args.partition, need_running=not args.any)
    elif args.action == "is-holder":
        return 0 if is_holder(args.job) else 1
    elif args.action == "info":
        record = holder(args.job)
        if record is None:
            raise ValueError(f"job {args.job} は確保ジョブではありません")
        print_fields(record)
    elif args.action == "enqueue":
        enqueue(args.job, args.run)
    elif args.action == "wait":
        return 0 if wait_running(args.job) else 1
    elif args.action == "dispatch":
        dispatch(args.folder)
    elif args.action == "partition":
        partition = args.partition or os.environ.get("AGENTRUN_SLURM_PARTITION", "") or default_partition()
        resources = partition_resources(partition)
        for value in (partition, resources["cpus"], resources["mem"], resources["gpus"], resources["limit"], resources["node"]):
            print(value)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print("hold: " + label(str(error)), file=sys.stderr)
        sys.exit(2)
