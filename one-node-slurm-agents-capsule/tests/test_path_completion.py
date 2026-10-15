"""実際の Bash/Readline で Tab を押し、起動前のパス補完を検証する。"""

import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BashCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="completion repo with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.capture = self.root / "args.json"
        self.env = dict(os.environ, HOME=str(self.home), INPUTRC="/dev/null", PS1="SHELL> ",
                        PROMPT_COMMAND="", TEST_COMPLETION=str(ROOT / "runtime/agentrun/agentrun.bash"),
                        TEST_CAPTURE=str(self.capture))

    def complete_and_run(self, line):
        master, slave = pty.openpty()

        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        before = termios.tcgetattr(slave)
        proc = subprocess.Popen(["bash", "--noprofile", "--norc", "-i"], cwd=self.root, env=self.env,
                                stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling_terminal)
        output = bytearray()

        def until_prompt():
            part = bytearray()
            deadline = time.monotonic() + 5
            while b"SHELL> " not in part:
                self.assertLess(time.monotonic(), deadline, repr(output + part))
                if select.select([master], [], [], .05)[0]:
                    part.extend(os.read(master, 65536))
            output.extend(part)

        try:
            until_prompt()
            script = '''source "$TEST_COMPLETION"
agentrun() { python3 -c 'import json, os, sys; from pathlib import Path; Path(os.environ["TEST_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))' "$@"; }
'''
            for statement in script.splitlines():
                os.write(master, statement.encode() + b"\n")
                until_prompt()
            os.write(master, line.encode() + b"\n")
            until_prompt()
            os.write(master, b"exit\n")
            proc.wait(timeout=5)
            self.assertEqual(proc.returncode, 0, output.decode(errors="replace"))
            self.assertEqual(termios.tcgetattr(slave), before)
            return json.loads(self.capture.read_text()), output.decode(errors="replace")
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            os.close(master)
            os.close(slave)

    def test_absolute_relative_and_quoted_bind_source(self):
        path = self.root / "unique space"
        path.mkdir()
        escaped_root = str(self.root).replace(" ", "\\ ")
        for prefix in ("uni", f"{escaped_root}/uni", f"{shlex.quote(str(self.root))}/uni",
                       f'"{self.root}/uni'):
            with self.subTest(prefix=prefix):
                args, _ = self.complete_and_run(f"agentrun assist --bind {prefix}\t:/extra:ro")
                source = "unique space/" if prefix == "uni" else f"{path}/"
                self.assertEqual(args, ["assist", "--bind", f"{source}:/extra:ro"])

    def test_resume_repeated_bind_and_tilde(self):
        path = self.home / "unique home"
        path.mkdir()
        args, _ = self.complete_and_run("agentrun resume run-id --bind /tmp:/first:ro --bind ~/uni\t:/second:rw")
        self.assertEqual(args, ["resume", "run-id", "--bind", "/tmp:/first:ro", "--bind", f"{path}/:/second:rw"])

    def test_metacharacters_in_filename_are_not_executed(self):
        path = self.root / "unique $(touch injected) 'quotes' [literal]"
        path.mkdir()
        args, _ = self.complete_and_run("agentrun assist --bind uni\t:/extra:ro")
        self.assertEqual(args[-1], f"{path.name}/:/extra:ro")
        self.assertFalse((self.root / "injected").exists())

    def test_multiple_candidates_and_file_source(self):
        (self.root / "alpha-one").mkdir()
        (self.root / "alpha-two").mkdir()
        (self.root / "unique.txt").write_text("file")
        args, output = self.complete_and_run("agentrun assist --bind alpha-\t\tone/:/extra:ro")
        self.assertEqual(args[-1], "alpha-one/:/extra:ro")
        self.assertIn("alpha-one/", output)
        self.assertIn("alpha-two/", output)
        args, _ = self.complete_and_run("agentrun assist --bind uni\t:/file:ro")
        self.assertEqual(args[-1], "unique.txt:/file:ro")

    def test_repo_and_goal_paths_and_prompt_fallback(self):
        (self.root / "unique repo").mkdir()
        (self.root / "goal.yaml").write_text("goal")
        args, _ = self.complete_and_run("agentrun experiment --repo uni\t --goal go\t -- 'literal prompt'")
        self.assertEqual(args, ["experiment", "--repo", "unique repo/", "--goal", "goal.yaml", "--", "literal prompt"])


class CompletionInstallTests(unittest.TestCase):
    def test_install_and_uninstall_completion_with_custom_data_home(self):
        with tempfile.TemporaryDirectory(prefix="completion install ") as tmp:
            root = Path(tmp)
            capsule = root / "capsule"
            capsule.mkdir()
            (capsule / "runtime/agentrun").mkdir(parents=True)
            (capsule / "secrets").mkdir()
            for name in ("install.sh", "uninstall.sh", "runtime/agentrun/agentrun",
                         "runtime/agentrun/agentrun.bash", "secrets/gh.env.example", "secrets/.env.example"):
                shutil.copy2(ROOT / name, capsule / name)
            home, data = root / "home", root / "custom data"
            home.mkdir()
            env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(data))
            command = home / ".local/bin/agentrun"
            completion = data / "bash-completion/completions/agentrun"

            def run(script, *args):
                result = subprocess.run([str(capsule / script), *args], env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            run("install.sh")
            self.assertFalse(command.exists())
            self.assertFalse(completion.exists())
            output = run("install.sh", "--apply")
            self.assertEqual(command.resolve(), capsule / "runtime/agentrun/agentrun")
            self.assertEqual(completion.resolve(), capsule / "runtime/agentrun/agentrun.bash")
            self.assertIn("source ", output)
            secret = capsule / "secrets/gh.env"
            self.assertEqual(secret.stat().st_mode & 0o777, 0o600)
            secret.write_text("# existing configuration\n")
            run("install.sh", "--apply")
            self.assertEqual(secret.read_text(), "# existing configuration\n")
            run("uninstall.sh")
            self.assertTrue(command.exists())
            self.assertTrue(completion.exists())
            run("uninstall.sh", "--apply")
            self.assertFalse(command.is_symlink())
            self.assertFalse(completion.is_symlink())
            self.assertTrue(secret.exists())


if __name__ == "__main__":
    unittest.main()
