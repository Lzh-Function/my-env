#!/usr/bin/env python3
"""srunとは独立にSlurm終了を確認し、応答しないローカルclientを停止する。"""

import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time


POLL_SECONDS = 30
QUERY_TIMEOUT = 5
EXIT_GRACE = 2
STOP_GRACE = 2
TERMINAL = {'COMPLETED', 'CANCELLED', 'FAILED', 'TIMEOUT', 'NODE_FAIL',
            'OUT_OF_MEMORY', 'BOOT_FAIL', 'DEADLINE'}


class SlurmMonitor:
    def __init__(self, run_dir):
        self.job_file = run_dir / 'live/slurm_job_id.txt'
        self.job_id = None
        self.missing = 0
        self.unavailable = False
        self.cancelled = lambda: False

    def query(self, command):
        # callerの表示用filterが「job消失」という誤判定を生まないようにする。
        env = {key: value for key, value in os.environ.items() if not key.startswith('SQUEUE_')}
        env['LC_ALL'] = 'C'
        if self.cancelled():
            return None
        # PIPEは孫processが保持するとcommunicateの回収まで固まる。
        # 照会専用のprocess groupと一時ファイルで、終了待ちを有限にする。
        with tempfile.TemporaryFile() as output:
            try:
                process = subprocess.Popen(command, stdout=output, stderr=subprocess.DEVNULL,
                                           start_new_session=True, env=env)
            except OSError:
                return None
            deadline = time.monotonic() + QUERY_TIMEOUT
            try:
                while process.poll() is None:
                    if self.cancelled() or time.monotonic() >= deadline:
                        return None
                    time.sleep(0.05)
                if process.returncode:
                    return None
                output.seek(0)
                raw = output.read(1024 * 1024 + 1)
                return raw.decode('utf-8', errors='replace') if len(raw) <= 1024 * 1024 else None
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=STOP_GRACE)
                except subprocess.TimeoutExpired:
                    pass

    def state(self):
        if self.job_id is None:
            try:
                value = self.job_file.read_text().strip()
            except OSError:
                return None
            if not re.fullmatch(r'[0-9]+', value):
                return None
            self.job_id = value
        result = self.query(['scontrol', '--oneliner', 'show', 'job', self.job_id])
        if result is not None:
            ident = re.search(r'\bJobId=([0-9]+)\b', result)
            state = re.search(r'\bJobState=([A-Z_+]+)', result)
            if ident and ident[1] == self.job_id and state:
                self.missing = 0
                self.unavailable = False
                # COMPLETING等のflag付き状態は終了済みと扱わない。
                return state[1] if state[1] in TERMINAL else None
        # MinJobAge経過後など、scontrolから消えたjobも確認する。
        # --jobsの「Invalid job id」は照会障害と区別できないため、own job全体を照会する。
        result = self.query(['squeue', '--noheader', '--all', '--states=all',
                             '--user', str(os.getuid()), '--format=%i|%T'])
        if result is None:
            self.missing = 0
            if not self.unavailable:
                print('Slurmのjob状態を取得できません。終了済みとは扱わず監視を継続します。', file=sys.stderr)
                self.unavailable = True
            return None
        self.unavailable = False
        for line in result.splitlines():
            fields = line.strip().split('|')
            if len(fields) != 2:
                self.missing = 0
                return None
            if fields[0] == self.job_id:
                self.missing = 0
                return fields[1] if fields[1] in TERMINAL else None
        self.missing += 1
        return 'TERMINATED' if self.missing >= 2 else None


def descendants(pid):
    found = []
    try:
        children = (Path('/proc') / str(pid) / 'task' / str(pid) / 'children').read_text().split()
    except OSError:
        return found
    for child in children:
        ident = int(child)
        found.append(ident)
        found.extend(descendants(ident))
    return found


def stop_client(process):
    children = descendants(process.pid)
    try:
        process.terminate()
        process.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        process.kill()
    except ProcessLookupError:
        pass
    # srunのローカル補助processにもrepoロックやTTYを残さない。
    for pid in reversed(children):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=STOP_GRACE)
    except subprocess.TimeoutExpired:
        print('ローカルsrunを回収できませんでした。ホスト側の終了処理を続行します。', file=sys.stderr)


def supervise(run_dir, command):
    stopped = 0

    def stop(signum, _frame):
        nonlocal stopped
        stopped = 128 + signum

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    try:
        # 同じTTY/sessionを使う。repoロック等のFDはsrunへ引き継がない。
        process = subprocess.Popen(command, close_fds=True)
    except OSError as exc:
        print(f'srunを起動できません: {exc}', file=sys.stderr)
        return 127
    monitor = SlurmMonitor(run_dir)
    monitor.cancelled = lambda: bool(stopped)
    next_poll = 0
    ended_at = None
    state = None
    while True:
        code = process.poll()
        if code is not None:
            return code if code >= 0 else 128 - code
        if stopped:
            stop_client(process)
            return stopped
        now = time.monotonic()
        if ended_at is not None and now - ended_at >= EXIT_GRACE:
            print(f'Slurm job {monitor.job_id}は{state}ですがsrunが終了しません。ローカルclientを停止します。',
                  file=sys.stderr)
            stop_client(process)
            return 124 if state == 'TIMEOUT' else 1
        if ended_at is None and now >= next_poll:
            state = monitor.state()
            if state:
                ended_at = time.monotonic()
            # job IDはcompute nodeの開始時に書かれる。記録前はRPCを送らない。
            next_poll = time.monotonic() + (POLL_SECONDS if monitor.job_id else 0.2)
        time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error('srun command is required')
    return supervise(args.run_dir, args.command)


if __name__ == '__main__':
    raise SystemExit(main())
