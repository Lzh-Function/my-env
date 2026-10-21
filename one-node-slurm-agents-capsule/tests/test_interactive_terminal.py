"""Local PTY regression tests; no Slurm, image, CLI, or credentials required.

Run with: python3 -m unittest discover -s tests -p 'test_*.py' -v
"""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "runtime/agentrun/agentrun"
MOCK_SRUN = r'''#!/usr/bin/env python3
import os
from pathlib import Path
import signal
import sys
import tty

assert os.isatty(0), "srun lost its terminal stdin"
assert "--pty" in sys.argv
assert "--nodes=1" in sys.argv, "capsule must request one node"
assert "--ntasks=1" in sys.argv, "capsule must override inherited task counts"
try:
    os.fstat(200)
except OSError:
    pass
else:
    raise AssertionError("srun inherited the repo lock FD")
Path(os.environ["TEST_SRUN_PID"]).write_text(str(os.getpid()))
# A TUI sets emulator modes and kernel terminal attributes independently.
os.write(1, b"\x1b[>17u\x1b[?1049h\x1b[>17u\x1b[>4;2m")
os.write(1, b"\x1b[?1003h\x1b[?1006h\x1b[?1004h\x1b[?2004h\x1b[?1h\x1b=\x1b[?25l")
tty.setraw(0)
os.write(1, b"MOCK_READY\n")
mode = os.environ["TEST_SRUN_MODE"]
if mode == "killed":
    os.kill(os.getpid(), signal.SIGKILL)
elif mode == "timeout":
    # Model srun returning after Slurm kills a remote job at its time limit.
    os.write(2, b"srun: error: TIME LIMIT\n")
    sys.exit(1)
elif mode == "failure":
    sys.exit(42)
elif mode == "input":
    assert os.read(0, 1) == b"x", "srun did not receive terminal input"
elif mode == "hold":
    while True:
        signal.pause()
elif mode in ("hung_timeout", "hung_cancelled", "active", "unavailable", "ignore_term"):
    if mode != "ignore_term":
        (Path(sys.argv[-1]).parent / 'live/slurm_job_id.txt').write_text('9001\n')
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        signal.pause()
'''


class InteractiveTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrun-pty-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        mock = self.bin / "srun"
        mock.write_text(MOCK_SRUN)
        mock.chmod(0o755)
        control = self.bin / 'scontrol'
        control.write_text('''#!/usr/bin/env python3
import os, sys
mode=os.environ['TEST_SRUN_MODE']
if mode == 'unavailable': sys.exit(1)
state={'hung_timeout':'TIMEOUT','hung_cancelled':'CANCELLED'}.get(mode,'RUNNING')
print('JobId=9001 JobState='+state)
''')
        control.chmod(0o755)
        queue = self.bin / 'squeue'
        queue.write_text('#!/bin/sh\nexit 1\n')
        queue.chmod(0o755)

    def read_until(self, master, proc, output, marker):
        deadline = time.monotonic() + 8
        while marker not in output:
            self.assertLess(time.monotonic(), deadline, repr(output))
            self.assertIsNone(proc.poll(), repr(output))
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))

    def run_session(self, mode, host_signal=None, redirect_stdout=False, finalize_hang=False, export_failure=False, export_hang=False):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        # Verify exact restoration, including a non-default erase character.
        before = termios.tcgetattr(slave)
        before[6][termios.VERASE] = b"\x08"
        termios.tcsetattr(slave, termios.TCSANOW, before)
        before = termios.tcgetattr(slave)

        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                   AGENTRUN_HISTORY_DIR=str(self.root / "central-history"),
                   TEST_EXPORT_FAILURE="1" if export_failure else "0",
                   TEST_EXPORT_HANG="1" if export_hang else "0",
                   TEST_FINALIZE_HANG="1" if finalize_hang else "0",
                   SLURM_NTASKS='2', SLURM_NNODES='2',
                   TEST_SRUN_MODE=mode, TEST_SRUN_PID=str(self.root / "srun.pid"))
        wrapper = self.bin / 'python3'
        wrapper.write_text(f'''#!{sys.executable}
import os, signal, sys, time
from pathlib import Path
if len(sys.argv)>2 and sys.argv[1].endswith('/sessions.py') and sys.argv[2]=='finalize' and os.environ['TEST_FINALIZE_HANG']=='1':
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    while True: time.sleep(1)
if len(sys.argv)>2 and sys.argv[1].endswith('/history.py') and sys.argv[2]=='export':
    if not (Path(sys.argv[3]) / 'home/.codex/auth.json').is_file():
        print('home removed before export',file=sys.stderr)
        sys.exit(99)
    if os.environ['TEST_EXPORT_FAILURE']=='1': sys.exit(2)
    if os.environ['TEST_EXPORT_HANG']=='1':
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        while True: time.sleep(1)
os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')
        wrapper.chmod(0o755)
        if export_hang:
            real_timeout = shutil.which('timeout')
            limiter = self.bin / 'timeout'
            limiter.write_text(f'''#!{sys.executable}
import os,sys
args=sys.argv[1:]
if args[:2]==['--kill-after=2s','120s']:
    args[:2]=['--kill-after=0.2s','0.3s']
os.execv({real_timeout!r}, [{real_timeout!r}, *args])
''')
            limiter.chmod(0o755)
        # Exercise planning and launching with synthetic credential staging.
        script = '''source "$1"
copy_auth_credentials() { printf 'test credential' > "$1/home/.codex/auth.json"; }
command_prepare assist --agent codex
'''
        stdout = (self.root / "stdout.log").open("wb") if redirect_stdout else slave
        if redirect_stdout:
            self.addCleanup(stdout.close)
        proc = subprocess.Popen(["bash", "-c", script, "bash", str(LAUNCHER)],
                                cwd=self.root, env=env, stdin=slave, stdout=stdout,
                                stderr=slave, preexec_fn=controlling_terminal)

        def stop_processes():
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

        self.addCleanup(stop_processes)
        output = bytearray()
        if host_signal or mode == "input" or mode in ('active', 'unavailable'):
            self.read_until(master, proc, output, b"MOCK_READY")
            if mode in ('active', 'unavailable'):
                time.sleep(0.5)
                self.assertIsNone(proc.poll())
                with (self.root / '.agentrun.lock').open('w') as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if host_signal:
                os.kill(proc.pid, host_signal)
            else:
                os.write(master, b"x")
        deadline = time.monotonic() + (20 if finalize_hang else 8)
        while proc.poll() is None:
            self.assertLess(time.monotonic(), deadline, repr(output))
            if select.select([master], [], [], 0.1)[0]:
                output.extend(os.read(master, 65536))
        while select.select([master], [], [], 0)[0]:
            output.extend(os.read(master, 65536))

        self.assertEqual(termios.tcgetattr(slave), before)
        runs = list((self.root / ".agent-runs").glob("*_assist_codex"))
        self.assertEqual(len(runs), 1)
        self.assertFalse((runs[0] / "home").exists())
        self.assertNotIn("home removed before export", (runs[0] / "live/history_export.log").read_text())
        if not export_failure:
            status = json.loads((runs[0] / "live/history_export.json").read_text())
            self.assertEqual(status['status'], 'failed' if export_hang else 'empty')
            if export_hang:
                self.assertIn('timed out', status['error'])
        self.assertTrue((runs[0] / "apptainer_exec.sh").exists())
        if not host_signal:
            self.assertIn(
                f"agentrun: 対話セッション終了（exit={proc.returncode}）".encode(),
                output,
            )
        # Verify that the actual emulator modes the mock enabled are disabled
        # AFTER its last output, separately from restoring kernel termios.
        cleanup = bytes(output).split(b"MOCK_READY")[-1]
        for mode_number in (1003, 1006, 1004, 2004, 1):
            self.assertIn(f"\x1b[?{mode_number}l".encode(), cleanup)
        for sequence in (b"\x1b>", b"\x1b[>4;0m", b"\x1b[?1049l", b"\x1b[?25h"):
            self.assertIn(sequence, cleanup)
        alternate, main = cleanup.split(b"\x1b[?1049l", 1)
        self.assertIn(b"\x1b[=0u", alternate)
        self.assertIn(b"\x1b[=0u", main)
        if host_signal:
            child_pid = int((self.root / "srun.pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        # The lock must be released so a subsequent session can start.
        with (self.root / ".agentrun.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return proc.returncode


    def test_export_failure_preserves_agent_exit_and_cleans_home(self):
        self.assertEqual(self.run_session("failure", export_failure=True), 42)


    def test_export_timeout_cleans_home_and_preserves_agent_exit(self):
        self.assertEqual(self.run_session("normal", export_hang=True), 0)

    def test_normal_exit(self):
        self.assertEqual(self.run_session("normal"), 0)

    def test_slurm_time_limit(self):
        self.assertEqual(self.run_session("timeout"), 1)

    def test_srun_sigkill(self):
        self.assertEqual(self.run_session("killed"), 137)

    def test_failure_exit_code(self):
        self.assertEqual(self.run_session("failure"), 42)

    def test_srun_startup_failure(self):
        (self.bin / "srun").write_text("#!/usr/bin/env bash\nexit 127\n")
        self.assertEqual(self.run_session("normal"), 127)

    def test_keyboard_stdin(self):
        self.assertEqual(self.run_session("input"), 0)

    def test_redirected_stdout(self):
        self.assertEqual(self.run_session("timeout", redirect_stdout=True), 1)

    def test_host_sigterm(self):
        self.assertEqual(self.run_session("hold", signal.SIGTERM), 143)

    def test_host_sigint(self):
        self.assertEqual(self.run_session("hold", signal.SIGINT), 130)

    def test_host_sighup(self):
        self.assertEqual(self.run_session("hold", signal.SIGHUP), 129)

    def test_slurm_timeout_with_stuck_term_ignoring_srun(self):
        self.assertEqual(self.run_session('hung_timeout'), 124)

    def test_slurm_cancelled_with_stuck_srun(self):
        self.assertEqual(self.run_session('hung_cancelled'), 1)

    def test_host_signal_stops_term_ignoring_srun(self):
        self.assertEqual(self.run_session('ignore_term', signal.SIGTERM), 143)

    def test_active_job_keeps_lock(self):
        self.assertEqual(self.run_session('active', signal.SIGTERM), 143)

    def test_controller_query_failure_does_not_release_lock(self):
        self.assertEqual(self.run_session('unavailable', signal.SIGTERM), 143)

    def test_hanging_finalizer_is_bounded_and_home_is_removed(self):
        self.assertEqual(self.run_session('normal', finalize_hang=True), 0)

    def test_no_tty(self):
        result = subprocess.run([str(LAUNCHER), "assist", "--agent", "codex"],
                                cwd=self.root, stdin=subprocess.DEVNULL,
                                capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"--submit", result.stderr)
        self.assertFalse((self.root / ".agent-runs").exists())


if __name__ == "__main__":
    unittest.main()
