#!/usr/bin/env python3
"""Write history notes every day from the user's crontab (`agentrun history schedule`).

The crontab line runs `run`, which saves running sessions and writes every saved conversation
(`history export-md DIR --live`), logs to the history directory and records how it ended so
`history list` can say when the last automatic export failed. Only the line marked with MARK
is ever added or removed; the rest of the crontab is kept as it is.
"""

import argparse
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from history_export import atomic_text, history_root, json_text
from obsidian_note import zone

MARK = "# agentrun-history-export"
CLOCK = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
LOG = "auto-export.log"
STATUS = "auto-export.json"
LOCK = "auto-export.lock"
LOG_LIMIT = 2 * 1024 * 1024  # keep the newest half once the log grows past this
# Settings that change where history lives or how times are shown must reach the cron job too.
CARRIED = ("AGENTRUN_HISTORY_DIR", "AGENTRUN_TIMEZONE")


def crontab_lines():
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True, check=False)
    if result.returncode:
        if "no crontab" in result.stderr.lower():
            return []
        raise RuntimeError("crontab を読めません: " + (result.stderr.strip() or f"exit={result.returncode}"))
    return result.stdout.splitlines()


def write_crontab(lines):
    text = "".join(line + "\n" for line in lines)
    result = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError("crontab を書き換えられません: " + (result.stderr.strip() or f"exit={result.returncode}"))


def local_clock(hour, minute):
    """The cron daemon's local time for HH:MM in the history time zone (Tokyo by default)."""
    wanted = datetime.now(zone()).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return wanted.astimezone()  # cron reads its schedule in the system's local time


def entry(directory, hour, minute):
    local = local_clock(hour, minute)
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   **{key: os.environ[key] for key in CARRIED if os.environ.get(key)}}
    command = " ".join(f"{key}={shlex.quote(value)}" for key, value in environment.items())
    command += f" {shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))} run {shlex.quote(str(directory))}"
    # cron turns a bare % into a newline; the shell drops the backslash again. The shell also
    # treats MARK as a comment, so it only labels the line.
    return f"{local.minute} {local.hour} * * * {command.replace('%', chr(92) + '%')} {MARK} {hour:02d}:{minute:02d}"


def installed():
    return [line for line in crontab_lines() if MARK in line]


def describe(line):
    """(HH:MM in the history time zone, target directory) of an installed line."""
    clock = line.split(MARK, 1)[1].strip()
    words = shlex.split(line.split(MARK, 1)[0].replace("\\%", "%"))
    directory = words[words.index("run") + 1] if "run" in words else "?"
    return clock, directory


def last_status():
    try:
        return json.loads((history_root() / STATUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def failure_notice():
    """A one-line warning when the newest automatic export failed, else ''."""
    status = last_status()
    if not isinstance(status, dict) or status.get("status") != "failed":
        return ""
    return (f"[注意] 毎日の自動書き出しが失敗しました（{status.get('finished_at', '?')}、exit={status.get('exit', '?')}）。"
            f"ログ: {history_root() / LOG}")


def install(directory, clock):
    match = CLOCK.fullmatch(clock)
    if not match:
        raise ValueError("--at は 04:00 のように 時:分 で指定してください")
    hour, minute = int(match.group(1)), int(match.group(2))
    directory = Path(directory).expanduser().resolve()
    lines = crontab_lines()
    kept = [line for line in lines if MARK not in line]
    line = entry(directory, hour, minute)
    write_crontab(kept + [line])
    history_root().mkdir(parents=True, exist_ok=True, mode=0o700)
    local = local_clock(hour, minute)
    print(f"毎日 {hour:02d}:{minute:02d}（{zone()}）に、{directory} へ会話履歴を書き出すように登録しました。")
    if local.utcoffset() != datetime.now(zone()).utcoffset():
        print(f"サーバーの時計では {local:%H:%M}（{local.tzname()}）です。")
    if len(kept) != len(lines):
        print("前の登録は置き換えました。")
    print("実行中のセッションも、その時点の内容で保存してから書き出します（--live と同じ）。")
    print(f"ログ: {history_root() / LOG}")


def remove():
    lines = crontab_lines()
    kept = [line for line in lines if MARK not in line]
    if len(kept) == len(lines):
        print("自動書き出しは登録されていません。")
        return
    write_crontab(kept)
    print("毎日の自動書き出しを解除しました。")


def show():
    lines = installed()
    if not lines:
        print("自動書き出しは登録されていません。")
        print("登録するには: agentrun history schedule <書き出し先> [--at 04:00]")
    for line in lines:
        clock, directory = describe(line)
        print(f"毎日 {clock}（{zone()}）に {directory} へ書き出します。")
    status = last_status()
    if isinstance(status, dict):
        result = {"success": "成功", "failed": "失敗", "running": "実行中"}.get(status.get("status"), status.get("status"))
        print(f"前回: {result}（開始 {status.get('started_at', '?')}、終了 {status.get('finished_at', '-')}）")
    print(f"ログ: {history_root() / LOG}")


def trim(log):
    try:
        if log.stat().st_size <= LOG_LIMIT:
            return
        with log.open("rb") as stream:
            stream.seek(-LOG_LIMIT // 2, os.SEEK_END)
            tail = stream.read()
        log.write_bytes(tail[tail.find(b"\n") + 1:])
    except OSError:
        pass


def now():
    return datetime.now(zone()).strftime("%Y-%m-%d %H:%M:%S")


def run(directory):
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = root / LOG
    trim(log)
    with (root / LOCK).open("a") as lock, log.open("a", encoding="utf-8") as output:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            output.write(f"\n== {now()} 前回の自動書き出しがまだ動いているので、今回はそちらに任せます ==\n")
            return 0
        started = now()
        atomic_text(root / STATUS, json_text({"status": "running", "started_at": started, "directory": directory}) + "\n")
        output.write(f"\n== {started} 自動書き出しを始めます: {directory} ==\n")
        output.flush()
        # The home directory, not wherever cron starts, so no stray .agent-runs is picked up by accident.
        code = subprocess.run([sys.executable, str(Path(__file__).with_name("history_index.py")), "export-md",
                               directory, "--live"], cwd=Path.home(), stdout=output, stderr=subprocess.STDOUT,
                              stdin=subprocess.DEVNULL, check=False).returncode
        finished = now()
        output.write(f"== {finished} " + ("終わりました" if code == 0 else f"失敗しました（exit={code}）") + " ==\n")
        atomic_text(root / STATUS, json_text({"status": "success" if code == 0 else "failed", "started_at": started,
                                              "finished_at": finished, "exit": code, "directory": directory}) + "\n")
        return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "remove", "show", "run"))
    parser.add_argument("directory", nargs="?")
    parser.add_argument("--at", default="04:00")
    options = parser.parse_args()
    os.umask(0o077)
    if options.action in ("install", "run") and not options.directory:
        parser.error(f"{options.action} には書き出し先のフォルダが必要です")
    if options.action == "install":
        install(options.directory, options.at)
    elif options.action == "remove":
        remove()
    elif options.action == "show":
        show()
    else:
        return run(options.directory)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print("history schedule: " + str(error), file=sys.stderr)
        sys.exit(2)
