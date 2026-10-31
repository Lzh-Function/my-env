#!/usr/bin/env python3
"""Keep an interactive container session usable after accidental suspension.

There is no controlling shell on the compute node to run ``fg``. Keep the
original PTY and process group, and continue stopped processes in this session.
"""

import os
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

SHUTDOWN_GRACE = 12


def process_tree(pid):
    """Read only descendants of our child, never unrelated jobs on the node."""
    result = []
    pending = [pid]
    while pending:
        ident = pending.pop()
        try:
            stat = Path(f"/proc/{ident}/stat").read_text()
            state = stat.rsplit(")", 1)[1].split()[0]
            children = Path(f"/proc/{ident}/task/{ident}/children").read_text()
        except (OSError, IndexError):
            continue
        result.append((ident, state))
        pending.extend(map(int, children.split()))
    return result


def send(pid, signum):
    try:
        os.kill(pid, signum)
    except ProcessLookupError:
        pass


def supervise(command):
    requested = 0

    def stop(signum, _frame):
        nonlocal requested
        # Ctrl+C is also used by interactive CLIs to cancel the current turn.
        # The foreground CLI receives it directly; keep supervising the session.
        if signum == signal.SIGINT and os.isatty(0):
            return
        requested = signum

    # A caught handler resets to SIG_DFL on exec, so the CLI can handle signals
    # normally. SIG_IGN would also disable job control in its subprocesses.
    signal.signal(signal.SIGTSTP, lambda *_: None)
    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    original = None
    foreground = None
    if os.isatty(0):
        original = termios.tcgetattr(0)
        foreground = os.tcgetpgrp(0)
        attrs = termios.tcgetattr(0)
        attrs[6][termios.VSUSP] = os.fpathconf(0, "PC_VDISABLE")
        termios.tcsetattr(0, termios.TCSANOW, attrs)
    try:
        try:
            process = subprocess.Popen(command, close_fds=True)
        except OSError as exc:
            print(f"対話CLIを起動できません: {exc}", file=sys.stderr)
            return 127
        ending = None
        targets = set()
        while True:
            tree = process_tree(process.pid)
            if requested and ending is None:
                ending = time.monotonic()
                targets.update(pid for pid, _ in tree)
                for pid in reversed([pid for pid, _ in tree]):
                    send(pid, requested)
                    send(pid, signal.SIGCONT)
            code = process.poll()
            if ending is not None:
                # Allow the existing review/auth shutdown to finish within
                # Slurm's KillWait, without waiting indefinitely for a CLI.
                if code is not None or time.monotonic() - ending >= SHUTDOWN_GRACE:
                    targets.update(pid for pid, _ in tree)
                    for pid in targets:
                        send(pid, signal.SIGKILL)
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                    return 128 + requested
            elif code is not None:
                return code if code >= 0 else 128 - code
            else:
                stopped = [pid for pid, state in tree if state == "T"]
                if stopped:
                    print(
                        "\r\n対話セッションの停止を検出しました。自動的に続行します（fgは不要です）。",
                        file=sys.stderr,
                        flush=True,
                    )
                    for pid in reversed(stopped):
                        send(pid, signal.SIGCONT)
            time.sleep(0.1)
    finally:
        if original is not None:
            try:
                # A CLI may have put itself in a separate foreground group.
                # Its exit must not leave the guard unable to restore the PTY.
                signal.signal(signal.SIGTTOU, signal.SIG_IGN)
                os.tcsetpgrp(0, foreground)
                termios.tcsetattr(0, termios.TCSANOW, original)
            except (OSError, termios.error):
                pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("terminal-session: command is required")
    raise SystemExit(supervise(sys.argv[1:]))
