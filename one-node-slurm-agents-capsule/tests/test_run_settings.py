"""Exercise saved launch settings, CLI preferences, and confirmation before resume."""

import fcntl
import importlib.util
import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import termios
import time
import unittest
from pathlib import Path

from test_sessions import codex_history, sessions

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
HELPER = ROOT / "runtime/agentrun/run_settings.py"
SPEC = importlib.util.spec_from_file_location("run_settings", HELPER)
settings = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(settings)


class RunSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='resume settings "quotes" ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "project"
        self.repo.mkdir()
        self.home = self.root / "host-home"
        self.home.mkdir()
        self.data = self.root / "data $(touch injected)"
        self.data.mkdir()
        self.secret = self.root / 'secrets "quoted",.env'
        self.secret.write_text("HF_TOKEN=synthetic-private-value\n")
        self.secret.chmod(0o600)
        self.goal = self.root / "original-goal.yaml"
        self.goal.write_text("objective: saved goal\n")
        self.env = dict(
            os.environ,
            HOME=str(self.home),
            AGENTRUN_SECRETS_FILE="",
            AGENT_REVIEW_CODEX_EFFORT="high",
        )
        self.run = self.root / ".agent-runs/original"

    def prepare(self, agent="codex"):
        script = """source "$1"; shift
broker_flag=--no-gh-broker
if [ -n "${TEST_GH_ENV_FILE:-}" ]; then DEFAULT_GH_ENV_FILE="$TEST_GH_ENV_FILE"; broker_flag=--gh-broker; fi
parse_run_args --repo "$1" --mem 8000M --cpus 3 --time 03:04:05 --gpus 2 --partition saved-partition \\
  --allow-fuse --bind "$2:/data:ro" --secrets-file "$3" "$broker_flag" --goal "$4"
write_plan experiment "$6" "$1" "$4" "$GPUS" "$TIME_LIMIT" task "$5" "$PARTITION" batch
"""
        result = subprocess.run(
            [
                "bash",
                "-c",
                script,
                "bash",
                str(LAUNCHER),
                str(self.repo),
                str(self.data),
                str(self.secret),
                str(self.goal),
                str(self.run),
                agent,
            ],
            check=False,
            cwd=self.root,
            env=self.env,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if agent == "codex":
            codex_history(sessions.state_dir(self.run, sessions.manifest(self.run)))
        return self.run

    def cleanup_home(self, run):
        result = subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; _agentrun_cleanup_home "$2"',
                "bash",
                str(ROOT / "runtime/agentrun/process-cleanup.sh"),
                str(run),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((run / "home").exists())

    def pty_resume(self, run, answer, *overrides):
        master, slave = pty.openpty()

        def terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        # Exercise the actual planner and confirmation; stop at the scheduler boundary.
        script = 'source "$1"; shift; run_interactive_session() { printf "LAUNCH_BOUNDARY\\n"; }; command_resume "$@"'
        proc = subprocess.Popen(
            ["bash", "-c", script, "bash", str(LAUNCHER), str(run), *overrides],
            cwd=self.root,
            env=self.env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            preexec_fn=terminal,  # noqa: PLW1509 -- single-threaded PTY test needs a controlling terminal
        )
        output, sent = bytearray(), False
        try:
            deadline = time.monotonic() + 10
            while proc.poll() is None:
                self.assertLess(time.monotonic(), deadline, output)
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
                if not sent and "この設定を引き継いで再開しますか？".encode() in output:
                    os.write(master, answer.encode() + b"\n")
                    sent = True
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))
            return proc.returncode, output.decode(errors="replace")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            os.close(master)
            os.close(slave)

    def test_launch_settings_survive_home_cleanup_and_run_rename(self):
        run = self.prepare()
        self.cleanup_home(run)
        renamed = run.with_name("original_title")
        run.rename(renamed)
        data = settings.load(renamed)
        self.assertEqual(data["options"]["mem"], "8000M")
        self.assertEqual(data["options"]["cpus"], "3")
        self.assertEqual(data["options"]["time"], "03:04:05")
        self.assertEqual(data["options"]["gpus"], "2")
        self.assertEqual(data["options"]["partition"], "saved-partition")
        self.assertEqual(data["binds"], [f"{self.data}:/data:ro"])
        self.assertTrue(data["allow_fuse"])
        self.assertEqual(data["secrets_file"], str(self.secret))
        self.assertEqual(data["review_env"], {"AGENT_REVIEW_CODEX_EFFORT": "high"})
        self.assertNotIn(
            "synthetic-private-value", (renamed / "launch.json").read_text()
        )
        self.assertEqual((renamed / "launch.json").stat().st_mode & 0o777, 0o600)
        self.assertIn(str(renamed / "goal.yaml"), settings.args(renamed))
        self.assertFalse((self.root / "injected").exists())

    def test_mutable_preferences_are_captured_before_cleanup_for_both_agents(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                self.run = self.root / ".agent-runs" / agent
                run = self.prepare(agent)
                file = run / "home" / settings.CONFIG[agent]
                if agent == "claude":
                    value = json.loads(file.read_text())
                    value["effortLevel"] = "medium"
                    file.write_text(json.dumps(value))
                else:
                    file.write_text(
                        'model_reasoning_effort = "low"\n' + file.read_text()
                    )
                expected = file.read_bytes()
                self.cleanup_home(run)
                self.assertEqual(settings.config_source(run).read_bytes(), expected)
                new = self.root / "restored" / agent
                settings.restore(run, new)
                self.assertEqual(
                    (new / "home" / settings.CONFIG[agent]).read_bytes(), expected
                )
                self.assertEqual(
                    settings.config_source(run).stat().st_mode & 0o777, 0o600
                )
                self.assertFalse(
                    any(
                        "auth.json" in p.name or "credentials" in p.name
                        for p in (run / "saved_settings").iterdir()
                    )
                )

    def test_old_launch_scripts_restore_mounts_gpu_partition_and_secrets(self):
        run = self.prepare()
        (run / "launch.json").unlink()
        data = settings.load(run)
        self.assertTrue(data["legacy"])
        self.assertEqual(data["binds"], [f"{self.data}:/data:ro"])
        self.assertEqual(data["options"]["gpus"], "2")
        self.assertEqual(data["options"]["partition"], "saved-partition")
        self.assertEqual(data["secrets_file"], str(self.secret))
        self.assertTrue(data["allow_fuse"])

    def test_declining_confirmation_does_not_allocate_or_mutate_source(self):
        run = self.prepare()
        before = (run / "session.json").read_bytes()
        rc, output = self.pty_resume(run, "n")
        self.assertEqual(rc, 0, output)
        self.assertIn("saved-partition", output)
        self.assertNotIn("LAUNCH_BOUNDARY", output)
        self.assertEqual((run / "session.json").read_bytes(), before)
        self.assertEqual(
            [p.name for p in run.parent.iterdir() if p.name.startswith("20")], []
        )

    def test_confirmed_resume_inherits_and_overrides_by_mount_destination(self):
        run = self.prepare()
        self.cleanup_home(run)
        replacement = self.root / "replacement"
        replacement.mkdir()
        rc, output = self.pty_resume(
            run, "y", "--bind", f"{replacement}:/data:rw", "--mem", "9000M"
        )
        self.assertEqual(rc, 0, output)
        self.assertIn("LAUNCH_BOUNDARY", output)
        resumed = (run.parent / "latest").resolve()
        self.assertNotEqual(resumed, run)
        data = settings.load(resumed)
        self.assertEqual(data["options"]["mem"], "9000M")
        self.assertEqual(data["options"]["cpus"], "3")
        self.assertEqual(data["options"]["gpus"], "2")
        self.assertEqual(data["options"]["partition"], "saved-partition")
        self.assertEqual(data["binds"], [f"{replacement}:/data:rw"])
        self.assertIn("--nv", (resumed / "apptainer_exec.sh").read_text())
        self.assertIn("--gres=gpu:2", (resumed / "submit.sbatch").read_text())

    def test_explicit_clearing_allows_resume_when_old_mount_or_secrets_disappear(self):
        run = self.prepare()
        self.cleanup_home(run)
        self.data.rmdir()
        self.secret.unlink()
        rc, output = self.pty_resume(
            run, "y", "--no-binds", "--no-secrets", "--no-allow-fuse"
        )
        self.assertEqual(rc, 0, output)
        data = settings.load((run.parent / "latest").resolve())
        self.assertEqual(data["binds"], [])
        self.assertEqual(data["secrets_file"], "")
        self.assertFalse(data["allow_fuse"])

    def test_fresh_config_skips_modified_agent_preferences(self):
        run = self.prepare()
        (run / "home/.codex/config.toml").write_text('model = "saved-model"\n')
        self.cleanup_home(run)
        rc, output = self.pty_resume(run, "y", "--fresh-config")
        self.assertEqual(rc, 0, output)
        resumed = (run.parent / "latest").resolve()
        self.assertNotIn(
            'model = "saved-model"', (resumed / "home/.codex/config.toml").read_text()
        )

    def test_capture_does_not_follow_replaced_config_directory(self):
        run = self.prepare()
        external = self.root / "external"
        external.mkdir()
        (external / "config.toml").write_text('model = "external-private-model"\n')
        shutil.rmtree(run / "home/.codex")
        (run / "home/.codex").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            settings.capture(run)
        self.assertNotIn(
            "external-private-model", (run / "saved_settings/config.toml").read_text()
        )

    def test_empty_old_mount_target_does_not_replace_valid_settings(self):
        run = self.prepare("claude")
        saved = (run / "saved_settings/settings.json").read_bytes()
        (run / "home/.claude/settings.json").write_text("")
        self.cleanup_home(run)
        self.assertEqual((run / "saved_settings/settings.json").read_bytes(), saved)
        self.assertIn("設定ファイルが空", (run / "live/home_cleanup.log").read_text())

    def test_capture_does_not_write_through_replaced_snapshot_directory(self):
        run = self.prepare()
        external = self.root / "external"
        external.mkdir()
        target = external / "config.toml"
        target.write_text('model = "keep-external-settings"\n')
        shutil.rmtree(run / "saved_settings")
        (run / "saved_settings").symlink_to(external, target_is_directory=True)
        with self.assertRaises(OSError):
            settings.capture(run)
        self.assertEqual(target.read_text(), 'model = "keep-external-settings"\n')

    def test_broker_reference_is_recovered_from_old_command_and_can_be_disabled(self):
        broker = self.root / 'gh "quoted",.env'
        broker.write_text("GH_TOKEN=synthetic-broker-token\n")
        broker.chmod(0o600)
        self.env["TEST_GH_ENV_FILE"] = str(broker)
        run = self.prepare()
        self.assertEqual(settings.load(run)["gh_env_file"], str(broker))
        (run / "launch.json").unlink()
        self.assertEqual(settings.load(run)["gh_env_file"], str(broker))
        broker.unlink()
        rc, output = self.pty_resume(run, "y", "--no-gh-broker")
        self.assertEqual(rc, 0, output)
        self.assertEqual(
            settings.load((run.parent / "latest").resolve())["gh_env_file"], ""
        )

    def test_explicit_reviewer_environment_overrides_saved_values(self):
        run = self.prepare()
        self.env["AGENT_REVIEW_CODEX_EFFORT"] = "low"
        rc, output = self.pty_resume(run, "y")
        self.assertEqual(rc, 0, output)
        self.assertEqual(
            settings.load((run.parent / "latest").resolve())["review_env"],
            {"AGENT_REVIEW_CODEX_EFFORT": "low"},
        )


if __name__ == "__main__":
    unittest.main()
