#!/usr/bin/env python3
"""Real Slurm + Apptainer integration. Only runs inside the isolated test cluster."""

import errno
import fcntl
import json
import os
import pty
import select
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import termios
import time
import traceback
import unittest
from pathlib import Path

CAPSULE = Path("/shared/capsule")
LAUNCHER = CAPSULE / "runtime/agentrun/agentrun"


def command(argv, **options):
    return subprocess.run(
        argv, check=False, capture_output=True, text=True, timeout=30, **options
    )


class Session:
    def __init__(self, repo, args, env=None):
        self.repo = repo
        self.master, self.slave = pty.openpty()
        self.before = termios.tcgetattr(self.slave)
        self.output = bytearray()
        self.run = None

        def terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)

        self.process = subprocess.Popen(
            [str(LAUNCHER), *args],
            cwd=repo,
            stdin=self.slave,
            stdout=self.slave,
            stderr=self.slave,
            preexec_fn=terminal,  # noqa: PLW1509 -- single-threaded PTY driver must acquire a controlling terminal
            env=env,
        )

    def pump(self, seconds=0.1):
        if select.select([self.master], [], [], seconds)[0]:
            try:
                self.output.extend(os.read(self.master, 65536))
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise

    def until(self, marker, seconds=60):
        deadline = time.monotonic() + seconds
        while marker not in self.output:
            self.pump()
            if marker in self.output:
                break
            if self.process.poll() is not None:
                raise AssertionError(
                    f"launcher exited {self.process.returncode}: {self.output!r}"
                )
            if time.monotonic() >= deadline:
                raise AssertionError(f"waiting for {marker!r}: {self.output!r}")
            self.pump()
        self.run = (self.repo / ".agent-runs/latest").resolve()
        return self.run

    def finish(self, seconds=150):
        deadline = time.monotonic() + seconds
        while self.process.poll() is None:
            if time.monotonic() >= deadline:
                raise AssertionError(f"launcher hung: {self.output!r}")
            self.pump()
        while select.select([self.master], [], [], 0)[0]:
            self.pump(0)
        after = termios.tcgetattr(self.slave)
        if after != self.before:
            raise AssertionError(
                f"TTY not restored: before={self.before!r} after={after!r} output={self.output!r}"
            )
        return self.process.returncode

    def close(self):
        if self.process.poll() is None:
            if self.run is None and (self.repo / ".agent-runs/latest").exists():
                self.run = (self.repo / ".agent-runs/latest").resolve()
            if self.run:
                job = self.run / "live/slurm_job_id.txt"
                if job.is_file() and job.read_text().strip().isdigit():
                    command(["scancel", job.read_text().strip()])
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait(timeout=3)
            except ProcessLookupError:
                pass
        (self.repo / f"terminal-{self.process.pid}.json").write_text(
            json.dumps(
                {
                    "pid": self.process.pid,
                    "exit_code": self.process.returncode,
                    "output": self.output.decode("utf-8", errors="replace"),
                }
            )
        )
        os.close(self.master)
        os.close(self.slave)


class ClusterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not Path("/etc/capsule-test-cluster").is_file():
            raise RuntimeError("Refusing to run outside the isolated Docker cluster")
        if any(shutil.which(name) for name in ("apptainer", "codex", "claude")):
            raise RuntimeError(
                "Controller must not have Apptainer or agent CLIs on PATH"
            )
        config = command(["scontrol", "show", "config"])
        if config.returncode or "one-node-capsule-test" not in config.stdout:
            raise RuntimeError(
                "Not connected to the isolated one-node-capsule-test cluster"
            )
        deadline = time.monotonic() + 180
        while (
            command(["sinfo", "--partition=agent", "-Nh", "-o", "%T"]).stdout.strip()
            != "idle"
        ):
            if time.monotonic() > deadline:
                raise RuntimeError("Compute node did not become idle")
            time.sleep(1)
        preflight = command(
            [
                "srun",
                "--nodes=1",
                "--ntasks=1",
                "--cpus-per-task=1",
                "--mem=512M",
                "--time=00:01:00",
                "apptainer",
                "exec",
                "--containall",
                "--cleanenv",
                "--no-home",
                "--no-mount",
                "hostfs,bind-paths,cwd",
                "--pwd",
                "/tmp",
                str(CAPSULE / "runtime/apptainer/base-system.sif"),
                "/bin/echo",
                "CAPSULE_APPTAINER_READY",
            ]
        )
        if preflight.returncode or "CAPSULE_APPTAINER_READY" not in preflight.stdout:
            raise RuntimeError(
                "Real nested Apptainer preflight failed; check Docker "
                "user namespaces, AppArmor and private cgroups.\n"
                + preflight.stdout
                + preflight.stderr
            )
        print("Real Slurm and Apptainer preflight passed", flush=True)
        cls.seed_auth()

    @staticmethod
    def seed_auth():
        for agent, relative in [
            ("codex", ".codex/auth.json"),
            ("claude", ".claude/.credentials.json"),
            ("claude", ".claude.json"),
        ]:
            path = Path.home() / ".agentrun/auth" / agent / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            path.write_text('{"synthetic":"offline-seed"}')
            path.chmod(0o600)

    def repo(self, name):
        path = Path(
            tempfile.mkdtemp(prefix=name + ' "quoted" spaces ', dir="/shared/work")
        )
        for args in (
            ["init", "-qb", "work"],
            ["config", "user.name", "Docker Fixture"],
            ["config", "user.email", "fixture@example.invalid"],
        ):
            result = command(["git", "-C", str(path), *args])
            self.assertEqual(result.returncode, 0, result.stderr)
        (path / "code.py").write_text("value = 1\n")
        command(["git", "-C", str(path), "add", "code.py"])
        result = command(["git", "-C", str(path), "commit", "-qm", "fixture base"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(self.logs, path)
        return path

    def logs(self, repo):
        for path in sorted((repo / ".agent-runs").glob("*/live/*")):
            if (
                path.parent.parent.name != "latest"
                and path.name
                in (
                    "slurm.err",
                    "stderr.log",
                    "history_export.log",
                )
                and path.is_file()
                and path.stat().st_size
            ):
                print(f"\n--- {path} ---\n{path.read_text()[-6000:]}", flush=True)

    def cli(self, repo, *args, expected=0, env=None):
        result = command([str(LAUNCHER), *map(str, args)], cwd=repo, env=env)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def options(self, repo, **values):
        (repo / ".capsule-test.json").write_text(json.dumps(values))

    def unlocked(self, repo):
        with (repo / ".agentrun.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def wait(self, predicate, seconds=100):
        deadline = time.monotonic() + seconds
        while True:
            value = predicate()
            if value:
                return value
            self.assertLess(
                time.monotonic(), deadline, "Timed out waiting for cluster state"
            )
            time.sleep(0.2)

    def batch(
        self,
        repo,
        agent="codex",
        mode="experiment",
        expected=0,
        extra=(),
        broker=False,
        env=None,
    ):
        result = self.cli(
            repo,
            mode,
            "--agent",
            agent,
            "--repo",
            repo,
            "--mem",
            "512M",
            "--cpus",
            "1",
            "--time",
            "00:03:00",
            *([] if broker else ["--no-gh-broker"]),
            *extra,
            "--submit",
            "offline fixture",
            env=env,
        )
        import re

        job = re.search(r"Submitted batch job (\d+)", result.stdout)
        self.assertIsNotNone(job, result.stdout)
        self.addCleanup(command, ["scancel", job[1]])

        def complete():
            run = (repo / ".agent-runs/latest").resolve()
            state = command(["scontrol", "show", "job", job[1]]).stdout
            terminal = any(
                "JobState=" + value in state
                for value in ("COMPLETED", "FAILED", "CANCELLED", "TIMEOUT")
            )
            return (
                run
                if terminal and (run / "live/session_finished.txt").is_file()
                else None
            )

        run = self.wait(complete)
        diagnostic = (run / "live/slurm.err").read_text() + (
            run / "live/stderr.log"
        ).read_text()
        self.assertEqual(
            int((run / "live/exit_code.txt").read_text()), expected, diagnostic
        )
        self.unlocked(repo)
        return run

    def session(self, repo, args, env=None):
        session = Session(repo, args, env)
        self.addCleanup(session.close)
        return session

    def assist(self, repo, agent="codex", limit="00:03:00", extra=()):
        return self.session(
            repo,
            [
                "assist",
                "--agent",
                agent,
                "--repo",
                str(repo),
                "--mem",
                "512M",
                "--cpus",
                "1",
                "--time",
                limit,
                "--no-gh-broker",
                *extra,
            ],
        )

    def ended(self, session):
        run = session.run
        self.assertFalse((run / "home").exists(), run)
        self.unlocked(session.repo)
        return run

    def archived(self, run):
        def status():
            path = run / "live/history_export.json"
            if not path.exists():
                return None
            data = json.loads(path.read_text())
            self.assertNotEqual(data["status"], "failed", data)
            return data if data["status"] == "success" else None

        data = self.wait(status, 35)
        self.assertEqual(data["archive_host"], "controller")
        markdown = Path(data["markdown"]).read_text()
        self.assertIn("capsule persisted conversation", markdown)
        self.assertIn("offline-output", markdown)
        metadata = json.loads(
            Path(data["markdown"]).with_name("metadata.json").read_text()
        )
        self.assertEqual(metadata["launcher_cwd"], str(run.parent.parent))
        with sqlite3.connect(data["database"]) as database:
            row = database.execute(
                "SELECT markdown, launcher_cwd, repo FROM conversations WHERE archive_id = ?",
                (data["archive_id"],),
            ).fetchone()
        self.assertEqual(row, (markdown, metadata["launcher_cwd"], metadata["repo"]))
        self.assertEqual(Path(data["database"]).stat().st_mode & 0o777, 0o600)
        return data, markdown

    def test_all_agents_all_profiles_real_batch_and_required_outputs(self):
        for agent in ("codex", "claude"):
            for mode in ("assist", "experiment", "campaign", "review", "multi-review"):
                with self.subTest(agent=agent, mode=mode):
                    repo = self.repo(agent + "-" + mode)
                    self.options(repo, hooks=True)
                    extra = []
                    if mode == "experiment":
                        goal = repo / "explicit goal.yaml"
                        goal.write_text("objective: fixture goal\n")
                        extra = ["--goal", str(goal)]
                    if mode == "review":
                        extra = [
                            "--reviewers",
                            "claude,codex",
                            "--target-diff",
                            "target.patch",
                        ]
                    if mode == "multi-review":
                        extra = ["--agents", "codex,claude"]
                    run = self.batch(repo, agent, mode, extra=extra)
                    self.assertEqual(
                        json.loads((run / "live/status.json").read_text())["status"],
                        "success",
                    )
                    self.assertTrue((repo / "workspace-write.txt").is_file())
                    metadata = json.loads(
                        (run / "artifacts/agent-cli.json").read_text()
                    )
                    self.assertIn("capsule-test-1", metadata["version"])
                    self.assertTrue(metadata["path"].startswith("/cache/agent-cli."))
                    self.cli(repo, "verify-run", run)
                    if mode == "experiment":
                        self.assertEqual(
                            (run / "goal.yaml").read_text(), goal.read_text()
                        )
                    resources = command(
                        [
                            "scontrol",
                            "show",
                            "job",
                            (run / "live/slurm_job_id.txt").read_text().strip(),
                        ]
                    )
                    self.assertIn("NumCPUs=1", resources.stdout)
                    self.assertIn("TimeLimit=00:03:00", resources.stdout)
                    self.archived(run)

    def test_interactive_completion_history_preview_and_resume_both_agents(self):
        for agent in ("codex", "claude"):
            with self.subTest(agent=agent):
                repo = self.repo("resume-" + agent)
                first = self.assist(repo, agent)
                original = first.until(("AGENT_READY:" + agent + ":").encode())
                self.assertEqual(first.finish(), 0, first.output)
                self.ended(first)
                self.archived(original)
                manifest = json.loads((original / "session.json").read_text())
                preview = self.cli(repo, "resume", original, "--preview")
                self.assertIn("capsule persisted conversation", preview.stdout)
                resumed = self.session(
                    repo,
                    [
                        "resume",
                        str(original),
                        "--time",
                        "00:03:00",
                        "--mem",
                        "512M",
                        "--cpus",
                        "1",
                    ],
                )
                resumed.until(
                    ("RESUME_OK:" + agent + ":" + manifest["native_id"]).encode()
                )
                self.assertEqual(resumed.finish(), 0, resumed.output)
                self.ended(resumed)
                current = json.loads((resumed.run / "session.json").read_text())
                self.assertEqual(current["session_key"], manifest["session_key"])
                self.assertNotEqual(resumed.run, original)
                self.archived(resumed.run)

    def test_scheduler_timeout_restores_terminal_and_allows_resume_for_both_agents(
        self,
    ):
        active = []
        for agent in ("codex", "claude"):
            repo = self.repo("timeout-" + agent)
            self.options(repo, hold=True)
            session = self.assist(repo, agent, limit="00:01:00")
            session.until(("AGENT_READY:" + agent + ":").encode())
            active.append((repo, agent, session))
        for repo, agent, session in active:
            with self.subTest(agent=agent):
                self.assertNotEqual(session.finish(seconds=150), 0)
                run = self.ended(session)
                job = (run / "live/slurm_job_id.txt").read_text().strip()
                self.wait(
                    lambda job=job: (
                        "JobState=TIMEOUT"
                        in command(["scontrol", "show", "job", job]).stdout
                    ),
                    65,
                )
                for reset in (
                    b"\x1b[?1003l",
                    b"\x1b[?1006l",
                    b"\x1b[?2004l",
                    b"\x1b[=0u",
                ):
                    self.assertIn(reset, session.output)
                self.options(repo)
                resumed = self.session(
                    repo,
                    [
                        "resume",
                        str(run),
                        "--time",
                        "00:03:00",
                        "--mem",
                        "512M",
                        "--cpus",
                        "1",
                    ],
                )
                resumed.until(("RESUME_OK:" + agent + ":").encode())
                self.assertEqual(resumed.finish(), 0, resumed.output)
                self.ended(resumed)

    def test_cancel_live_job_and_reject_concurrent_run(self):
        repo = self.repo("cancel-lock")
        self.options(repo, hold=True)
        first = self.assist(repo)
        run = first.until(b"AGENT_READY:codex:")
        second = self.assist(repo)
        self.assertNotEqual(second.finish(seconds=20), 0)
        self.assertIn(b"another agentrun", second.output)
        self.assertTrue((run / "home").exists())
        job = (run / "live/slurm_job_id.txt").read_text().strip()
        self.assertEqual(command(["scancel", job]).returncode, 0)
        self.assertNotEqual(first.finish(), 0)
        self.ended(first)

    def test_agent_download_and_installer_failures_allow_retry(self):
        for agent in ("codex", "claude"):
            for option, expected in [
                ("exit_code", 23),
                ("download_failure", 6),
                ("installer_failure", 42),
            ]:
                with self.subTest(agent=agent, option=option):
                    repo = self.repo("failure-" + agent + "-" + option)
                    self.options(repo, **{option: expected})
                    run = self.batch(repo, agent, expected=expected)
                    self.assertFalse((run / "home").exists())
                    self.assertEqual(
                        json.loads((run / "live/status.json").read_text())["status"],
                        "failed",
                    )
                    self.options(repo)
                    self.batch(repo, agent)

    def test_extra_binds_secrets_and_node_local_ssd(self):
        repo = self.repo("binds-secrets")
        ro, rw = repo / "read only", repo / "read write"
        for path in (ro, rw):
            path.mkdir()
            (path / "source.txt").write_text("host data")
        secrets = repo.parent / (repo.name + ",file.env")
        secrets.write_text("HF_TOKEN=CAPSULE_SYNTHETIC_HF_TOKEN\n")
        secrets.chmod(0o600)
        self.options(
            repo,
            secrets=True,
            mounts=[
                {"path": "/extra-ro", "writable": False},
                {"path": "/extra-rw", "writable": True},
            ],
        )
        run = self.batch(
            repo,
            extra=[
                "--bind",
                f"{ro}:/extra-ro:ro",
                "--bind",
                f"{rw}:/extra-rw:rw",
                "--secrets-file",
                str(secrets),
            ],
        )
        self.assertFalse((ro / "written.txt").exists())
        self.assertEqual((rw / "written.txt").read_text(), "container data")
        self.assertFalse(
            Path("/scratch/capsule").exists(), "Controller sees node-local SSD"
        )
        result = command(
            [
                "srun",
                "--mem=512M",
                "--cpus-per-task=1",
                "--time=00:01:00",
                "cat",
                "/scratch/capsule/fixture-write.txt",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "SSD data")
        self.assertNotIn(
            "CAPSULE_SYNTHETIC_HF_TOKEN",
            (run / "artifacts/environment.txt").read_text(),
        )

    def test_absent_node_local_ssd_is_not_created_and_run_still_starts(self):
        self.addCleanup(
            command,
            [
                "srun",
                "--mem=512M",
                "--time=00:01:00",
                "mv",
                "/scratch/disabled",
                "/scratch/capsule",
            ],
        )
        moved = command(
            [
                "srun",
                "--mem=512M",
                "--time=00:01:00",
                "mv",
                "/scratch/capsule",
                "/scratch/disabled",
            ]
        )
        self.assertEqual(moved.returncode, 0, moved.stderr)
        repo = self.repo("no-ssd")
        self.options(repo, ssd=False)
        self.batch(repo)
        result = command(
            [
                "srun",
                "--mem=512M",
                "--time=00:01:00",
                "test",
                "!",
                "-e",
                "/scratch/capsule",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_github_broker_real_sibling_container_and_token_isolation(self):
        repo = self.repo("github-broker")
        token = CAPSULE / "secrets/gh.env"
        token.write_text(
            "GH_TOKEN=CAPSULE_DOCKER_SYNTHETIC_TOKEN\nGH_BROKER_REPOS=owner/repo\n"
        )
        token.chmod(0o600)
        self.addCleanup(token.unlink, missing_ok=True)
        self.options(repo, gh=True)
        run = self.batch(repo, agent="claude", broker=True)
        self.assertNotIn(
            "CAPSULE_DOCKER_SYNTHETIC_TOKEN", (run / "live/gh_broker.log").read_text()
        )

    def test_github_broker_env_filename_with_quotes_and_comma(self):
        import re

        repo = self.repo("gh-env-file")
        token = repo.parent / (repo.name + ",broker.env")
        token.write_text(
            "GH_TOKEN=CAPSULE_DOCKER_SYNTHETIC_TOKEN\nGH_BROKER_REPOS=owner/repo\n"
        )
        token.chmod(0o600)
        self.options(repo, gh=True)
        # Override only the configured file location; use the production main,
        # planner, Slurm wrapper and broker containers without replacing them.
        result = command(
            [
                "bash",
                "-c",
                'source "$1"; DEFAULT_GH_ENV_FILE="$2"; main "${@:3}"',
                "bash",
                str(LAUNCHER),
                str(token),
                "experiment",
                "--agent",
                "claude",
                "--repo",
                str(repo),
                "--mem",
                "512M",
                "--cpus",
                "1",
                "--time",
                "00:03:00",
                "--submit",
                "offline fixture",
            ],
            cwd=repo,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        job = re.search(r"Submitted batch job (\d+)", result.stdout)
        self.assertIsNotNone(job, result.stdout)
        self.addCleanup(command, ["scancel", job[1]])
        self.wait(
            lambda: (
                "JobState=COMPLETED"
                in command(["scontrol", "show", "job", job[1]]).stdout
            )
        )
        run = (repo / ".agent-runs/latest").resolve()
        self.assertEqual(
            (run / "live/exit_code.txt").read_text().strip(),
            "0",
            (run / "live/stderr.log").read_text(),
        )
        self.assertNotIn(
            "CAPSULE_DOCKER_SYNTHETIC_TOKEN", (run / "live/gh_broker.log").read_text()
        )
        self.unlocked(repo)

    def test_cross_review_both_providers_cli_mcp_and_central_archive(self):
        for agent in ("codex", "claude"):
            for transport in ("cli", "mcp"):
                with self.subTest(agent=agent, transport=transport):
                    repo = self.repo("review-" + agent + "-" + transport)
                    self.options(repo, review=transport)
                    run = self.batch(repo, agent)
                    state = json.loads(
                        (run / "artifacts/dialogue-check.json").read_text()
                    )
                    self.assertEqual(state["verdict"], "approve")
                    self.assertEqual(state["round"], 2)
                    peer = "claude" if agent == "codex" else "codex"
                    manifest = json.loads((run / "session.json").read_text())
                    store = (
                        run.parent
                        / ".sessions"
                        / manifest["session_key"]
                        / "reviewers"
                        / peer
                    )
                    calls = [
                        json.loads(line)
                        for line in (store / "fixture-calls.jsonl")
                        .read_text()
                        .splitlines()
                    ]
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(calls[0]["session"], calls[1]["session"])
                    self.assertNotEqual(calls[1]["session"], calls[2]["session"])
                    _data, markdown = self.archived(run)
                    self.assertIn("Why this value?", markdown)
                    self.assertIn("A fixture defect", markdown)
                    self.assertIn("reviewer", markdown.lower())
                    self.cli(repo, "history", run)

    def test_missing_peer_auth_does_not_prevent_worker_startup(self):
        for worker, peer, relative in [
            ("claude", "codex", ".codex/auth.json"),
            ("codex", "claude", ".claude/.credentials.json"),
        ]:
            with self.subTest(worker=worker):
                moved = []
                try:
                    for original in (
                        Path.home() / ".agentrun/auth" / peer / relative,
                        Path.home() / relative,
                    ):
                        if original.exists():
                            backup = original.with_name(
                                original.name + ".docker-backup"
                            )
                            original.rename(backup)
                            moved.append((original, backup))
                    repo = self.repo("missing-peer-" + peer)
                    self.options(repo, review_negative="missing-auth")
                    self.batch(repo, agent=worker)
                finally:
                    for original, backup in moved:
                        backup.rename(original)

    def test_reviewer_timeout_is_reported_and_worker_continues(self):
        for worker in ("codex", "claude"):
            with self.subTest(worker=worker):
                repo = self.repo("review-timeout-" + worker)
                self.options(repo, review_negative="timeout")
                self.batch(
                    repo,
                    agent=worker,
                    env=dict(os.environ, AGENT_REVIEW_ACTIVE_TIMEOUT="1"),
                )

    def test_launcher_sigterm_cancels_allocation_and_releases_lock(self):
        repo = self.repo("launcher-signal")
        self.options(repo, hold=True)
        session = self.assist(repo)
        run = session.until(b"AGENT_READY:codex:")
        job = (run / "live/slurm_job_id.txt").read_text().strip()
        os.kill(session.process.pid, signal.SIGTERM)
        self.assertNotEqual(session.finish(seconds=80), 0)
        self.ended(session)
        self.wait(
            lambda: (
                "RUNNING" not in command(["squeue", "-h", "-j", job, "-o", "%T"]).stdout
            )
        )

    def test_pending_allocation_signal_leaves_no_queued_job(self):
        repo = self.repo("pending-signal")
        marker = repo / "blocker-ready"
        blocker = subprocess.Popen(
            [
                "srun",
                "--partition=agent",
                "--nodes=1",
                "--ntasks=1",
                "--cpus-per-task=4",
                "--mem=512M",
                "--time=00:03:00",
                "bash",
                "-c",
                'touch "$1"; sleep 120',
                "bash",
                str(marker),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def stop_blocker():
            if blocker.poll() is None:
                blocker.terminate()
                try:
                    blocker.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    blocker.kill()
                    blocker.wait(timeout=5)

        self.addCleanup(stop_blocker)
        self.wait(marker.exists, 35)
        session = self.assist(repo)
        run = session.until(b"launching interactive session")

        def pending():
            rows = command(
                ["squeue", "-h", "-u", str(os.getuid()), "-o", "%A|%T"]
            ).stdout.splitlines()
            return [row.split("|")[0] for row in rows if row.endswith("|PENDING")]

        jobs = self.wait(pending, 30)
        for job in jobs:
            self.addCleanup(command, ["scancel", job])
        os.kill(session.process.pid, signal.SIGTERM)
        self.assertNotEqual(session.finish(seconds=45), 0)
        self.assertFalse((run / "home").exists())
        self.unlocked(repo)
        self.wait(lambda: not pending(), 30)

    def test_plain_wizard_resumes_through_real_slurm(self):
        import re

        repo = self.repo("wizard")
        seed = self.batch(repo)
        env = dict(os.environ, WIZARD_UI="plain")
        session = self.session(
            repo,
            [
                "wizard",
                "--agent",
                "codex",
                "--time",
                "00:03:00",
                "--mem",
                "512M",
                "--cpus",
                "1",
                "--no-gh-broker",
            ],
            env,
        )
        replies = ["6", "1", "y", "", "", "", "n", "y"]
        prompts = re.compile(
            rb"#\? \(Enter=1, :back, :cancel\) |(?:\x1b\[\?2004h)?> |\(:back, :cancel\): "
        )
        sent = 0
        deadline = time.monotonic() + 70
        while b"RESUME_OK:codex:" not in session.output:
            session.pump()
            matches = list(prompts.finditer(session.output))
            while sent < len(matches) and sent < len(replies):
                os.write(session.master, replies[sent].encode() + b"\n")
                sent += 1
            self.assertIsNone(session.process.poll(), session.output)
            self.assertLess(time.monotonic(), deadline, session.output)
        session.run = (repo / ".agent-runs/latest").resolve()
        self.assertEqual(session.finish(seconds=60), 0, session.output)
        self.assertIn(b"Same run without the wizard:", session.output)
        self.assertNotEqual(self.ended(session), seed)

    def test_stuck_host_finalizer_is_bounded_and_native_history_can_resume(self):
        repo = self.repo("stuck-finalizer")
        binary = repo / "host tools"
        binary.mkdir()
        wrapper = binary / "python3"
        wrapper.write_text("""#!/usr/bin/python3
import os,signal,sys,time
if len(sys.argv)>2 and sys.argv[1].endswith('/sessions.py') and sys.argv[2]=='finalize':
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    while True: time.sleep(1)
os.execv('/usr/bin/python3',['/usr/bin/python3',*sys.argv[1:]])
""")
        wrapper.chmod(0o755)
        env = dict(os.environ, PATH=str(binary) + ":" + os.environ["PATH"])
        first = self.session(
            repo,
            [
                "assist",
                "--agent",
                "codex",
                "--mem",
                "512M",
                "--cpus",
                "1",
                "--time",
                "00:03:00",
                "--no-gh-broker",
            ],
            env,
        )
        run = first.until(b"AGENT_READY:codex:")
        self.assertEqual(first.finish(seconds=45), 0, first.output)
        self.ended(first)
        self.assertIn("終了記録を完了できません".encode(), first.output)
        resumed = self.session(
            repo,
            ["resume", str(run), "--mem", "512M", "--cpus", "1", "--time", "00:03:00"],
        )
        resumed.until(b"RESUME_OK:codex:")
        self.assertEqual(resumed.finish(), 0, resumed.output)
        self.ended(resumed)

    def test_auth_import_login_reset_and_shared_skills(self):
        repo = self.repo("auth-skills")
        binary = repo / "host tools"
        binary.mkdir()
        for agent in ("codex", "claude"):
            shutil.copyfile("/opt/cluster-test/fixtures/agent.py", binary / agent)
            (binary / agent).chmod(0o755)
        env = dict(os.environ, PATH=str(binary) + ":" + os.environ["PATH"])
        self.addCleanup(self.seed_auth)
        for agent in ("codex", "claude"):
            self.cli(repo, "auth", "reset", "--agent", agent)
        self.cli(repo, "auth", "login", "--all", env=env)
        self.cli(repo, "auth", "import", "--all")
        status = self.cli(repo, "auth", "status").stdout
        self.assertIn("store:present", status)
        self.batch(repo, agent="claude")
        source = repo / "skill source/skills/docker-fixture"
        source.mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: docker-fixture\ndescription: Offline fixture.\n---\nfirst\n"
        )
        target = CAPSULE / "common/skills/docker-fixture"
        self.addCleanup(shutil.rmtree, target, True)
        self.cli(repo, "skill-install", source.parent.parent)
        (source / "SKILL.md").write_text("second\n")
        self.cli(repo, "skill-install", source.parent.parent)
        self.assertIn("first", (target / "SKILL.md").read_text())
        self.cli(repo, "skill-install", source.parent.parent, "--force")
        self.assertEqual((target / "SKILL.md").read_text(), "second\n")
        self.cli(repo, "sync-claude")
        self.cli(repo, "sync-codex")
        self.cli(repo, "validate")

    def test_validate_doctor_goal_dry_run_smoke_and_run_commands(self):
        repo = self.repo("commands")
        for args in [("validate",), ("doctor", "--all"), ("agents",), ("init-goal",)]:
            self.cli(repo, *args)
        self.cli(repo, "init-goal", expected=2)
        for mode in ("assist", "experiment", "campaign", "review", "multi-review"):
            self.cli(repo, "dry-run", mode, "--show-mounts", "fixture")
        self.assertFalse((repo / ".agent-runs").exists())
        run = self.batch(repo)
        for args in [
            ("status",),
            ("logs",),
            ("list-runs",),
            ("open-run",),
            ("verify-run", run),
            ("resume", "--list"),
        ]:
            self.cli(repo, *args)
        self.cli(repo, "smoke-test", "--mem", "512M", "--submit")
        self.wait(
            lambda: (repo / ".agent-runs/latest/live/exit_code.txt").read_text().strip()
        )
        self.cli(repo, "verify-run", repo / ".agent-runs/latest")


class ImmediateResult(unittest.TextTestResult):
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err:
            self.stream.write("".join(traceback.format_exception(*err)))


class Runner(unittest.TextTestRunner):
    resultclass = ImmediateResult


if __name__ == "__main__":
    unittest.main(verbosity=2, testRunner=Runner)
