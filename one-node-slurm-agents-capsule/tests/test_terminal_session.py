"""Exercise the compute-side suspension guard with a real controlling PTY."""

import fcntl
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "runtime/agentrun/terminal-session.py"


class TerminalSessionTests(unittest.TestCase):
    def execute(self, script, action=None, shell=False, ancestor=False):
        with tempfile.TemporaryDirectory() as temp:
            child = Path(temp) / "cli.py"
            child.write_text(script)
            master, slave = pty.openpty()
            before = termios.tcgetattr(slave)

            def terminal():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            command = [sys.executable, str(child)]
            if shell:
                command = ["bash", "-c", '"$@"; exit "$?"', "bash", *command]
            guarded = [sys.executable, str(GUARD), *command]
            if ancestor:
                guarded = [
                    "bash",
                    "-c",
                    'trap "" TSTP; "$@"; exit "$?"',
                    "bash",
                    *guarded,
                ]
            proc = subprocess.Popen(
                guarded, stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=terminal,  # noqa: PLW1509 -- this PTY test uses no threads
            )
            output = bytearray()
            acted = False
            deadline = time.monotonic() + 18
            try:
                while proc.poll() is None:
                    self.assertLess(time.monotonic(), deadline, repr(output))
                    if select.select([master], [], [], 0.05)[0]:
                        output.extend(os.read(master, 65536))
                    if action and not acted and b"READY" in output:
                        action(proc, master)
                        acted = True
                while select.select([master], [], [], 0)[0]:
                    output.extend(os.read(master, 65536))
                self.assertEqual(termios.tcgetattr(slave), before)
                return proc.returncode, bytes(output)
            finally:
                if proc.poll() is None:
                    os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=3)
                os.close(master)
                os.close(slave)

    def test_ctrl_z_during_cooked_mode_keeps_session_usable(self):
        script = """import os, termios
assert termios.tcgetattr(0)[6][termios.VSUSP] == b'\\x00'
print('READY', flush=True)
assert input().strip() == '\\x1ahello'
print('INPUT_OK', flush=True)
"""
        code, output = self.execute(
            script, lambda proc, master: os.write(master, b"\x1ahello\n")
        )
        self.assertEqual(code, 0, output)
        self.assertIn(b"INPUT_OK", output)

    def test_cli_self_suspend_in_raw_mode_repeatedly_resumes_without_fg(self):
        script = """import os, signal, tty
tty.setraw(0)
for index in range(2):
    os.kill(os.getpid(), signal.SIGSTOP)
    print('CONTINUED', index, flush=True)
print('READY', flush=True)
assert os.read(0, 1) == b'x'
print('INPUT_OK', flush=True)
"""
        for shell in (False, True):
            with self.subTest(shell=shell):
                code, output = self.execute(
                    script, lambda proc, master: os.write(master, b"x"), shell=shell
                )
                self.assertEqual(code, 0, output)
                self.assertEqual(output.count(b"CONTINUED"), 2, output)
                self.assertEqual(output.count("自動的に続行".encode()), 2, output)
                self.assertIn(b"INPUT_OK", output)

    def test_real_sigtstp_after_cli_reenables_susp_is_continued(self):
        script = """import os, signal, termios
# Separate foreground process group with a parent in the same session, so
# SIGTSTP is not discarded as an orphaned-group signal by the kernel.
os.setpgrp()
signal.signal(signal.SIGTTOU, signal.SIG_IGN)
os.tcsetpgrp(0, os.getpgrp())
attrs = termios.tcgetattr(0)
attrs[6][termios.VSUSP] = b'\\x1a'
attrs[3] &= ~termios.ECHO
termios.tcsetattr(0, termios.TCSANOW, attrs)
print('READY', flush=True)
assert input() == 'hello'
print('INPUT_OK', flush=True)
"""
        code, output = self.execute(
            script, lambda proc, master: os.write(master, b"\x1ahello\n")
        )
        self.assertEqual(code, 0, output)
        self.assertIn("自動的に続行".encode(), output)
        self.assertIn(b"INPUT_OK", output)

    def test_group_directed_sigtstp_keeps_guard_and_outer_shell_usable(self):
        script = """import os, signal, tty
assert signal.getsignal(signal.SIGTSTP) == signal.SIG_DFL
tty.setraw(0)
os.kill(0, signal.SIGTSTP)
print('READY', flush=True)
assert os.read(0, 1) == b'x'
print('INPUT_OK', flush=True)
"""
        code, output = self.execute(
            script, lambda proc, master: os.write(master, b"x"), ancestor=True
        )
        self.assertEqual(code, 0, output)
        self.assertIn(b"INPUT_OK", output)

    def test_termination_still_stops_a_cli_that_ignores_term(self):
        script = """import signal, time, tty
tty.setraw(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print('READY', flush=True)
while True: time.sleep(1)
"""
        code, output = self.execute(script, lambda proc, master: proc.terminate())
        self.assertEqual(code, 143, output)

    def test_ctrl_c_can_cancel_a_turn_without_ending_the_session(self):
        script = """import signal
signal.signal(signal.SIGINT, lambda *_: print('TURN_CANCELLED', flush=True))
print('READY', flush=True)
assert input() == 'hello'
print('INPUT_OK', flush=True)
"""

        def cancel(proc, master):
            os.killpg(proc.pid, signal.SIGINT)
            os.write(master, b"hello\n")

        code, output = self.execute(script, cancel)
        self.assertEqual(code, 0, output)
        self.assertIn(b"TURN_CANCELLED", output)
        self.assertIn(b"INPUT_OK", output)

    def test_cli_exit_code_is_preserved(self):
        code, output = self.execute("raise SystemExit(42)")
        self.assertEqual(code, 42, output)


if __name__ == "__main__":
    unittest.main()
