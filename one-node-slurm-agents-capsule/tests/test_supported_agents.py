"""Exercise the supported agent boundary without Slurm, network, or real credentials."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
AGENTS = ("codex", "claude", "antigravity")
# CLI or product names that are not agent names.
UNKNOWN_AGENTS = ("agy", "gemini")


class SupportedAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="supported agents ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home))
        self.env.pop("AGENTRUN_SECRETS_FILE", None)

    def run_cli(self, *args, launcher=LAUNCHER):
        return subprocess.run([str(launcher), *map(str, args)], cwd=self.root, env=self.env,
                              text=True, capture_output=True, timeout=10)

    def source(self, script, *args):
        return subprocess.run(["bash", "-c", 'source "$1"; shift; ' + script,
                               "bash", str(LAUNCHER), *map(str, args)],
                              cwd=self.root, env=self.env, text=True, capture_output=True, timeout=10)

    def test_listing_and_default_select_only_supported_agents(self):
        result = self.run_cli("agents")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line.split()[0] for line in result.stdout.splitlines()[1:]], list(AGENTS))
        # Antigravity is found by its CLI name.
        self.assertIn("（agy コマンドが見つかりません）", result.stdout) if not shutil.which("agy") else None
        result = self.run_cli("dry-run", "assist", "--no-secrets")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected_agent: claude", result.stdout)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_every_agent_prepares_every_profile_with_shared_assets(self):
        for agent in AGENTS:
            for mode in ("assist", "experiment", "campaign"):
                with self.subTest(agent=agent, mode=mode):
                    # Exercise planning without starting or submitting a job.
                    result = self.source('parse_run_args --no-secrets; write_plan "$1" "$2" "$PWD" "" 0 00:10:00 task "$3" "" batch',
                                         mode, agent, self.root / f"{mode}_{agent}")
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    run = self.root / f"{mode}_{agent}"
                    command = (run / "apptainer_exec.sh").read_text()
                    self.assertIn(f"install-agent.sh {agent}", shlex.split(command.splitlines()[-1])[-1])
                    self.assertIn(f"agents/{agent}/", command)
                    self.assertIn("common/skills", command)
                    self.assertEqual(json.loads((run / "session.json").read_text())["agent"], agent)
                    # reviews/ holds cross-review records only; the removed review modes left no placeholders.
                    self.assertTrue((run / "reviews").is_dir())
                    self.assertEqual(list((run / "reviews").iterdir()), [])
                    for other in AGENTS:
                        if other != agent:
                            self.assertNotIn(f"agents/{other}/", command)
                            self.assertNotIn(f"install-agent.sh {other}", command)
                    if agent == "antigravity":
                        home = run / "home/.gemini"
                        settings = json.loads((home / "antigravity-cli/settings.json").read_text())
                        self.assertEqual(settings["toolPermission"], "always-proceed")
                        if shutil.which("jq"):  # the mode overlay is merged with jq, as for Claude Code
                            self.assertEqual(settings.get("runtimeProfile"), None if mode == "campaign" else mode)
                        mcp = json.loads((home / "config/mcp_config.json").read_text())
                        self.assertEqual(mcp["mcpServers"]["cross-review"]["command"], "/opt/agentrun/agent-review")
                        for target in ("/home/sandbox/.gemini/GEMINI.md", "/home/sandbox/.gemini/config/skills",
                                       "/home/sandbox/.gemini/config/hooks.json",
                                       "/home/sandbox/.gemini/antigravity-cli/brain",
                                       "/home/sandbox/.gemini/antigravity-cli/conversations"):
                            self.assertIn(target, command)
                        self.assertIn("agy --dangerously-skip-permissions --print-timeout 0 --print",
                                      shlex.split(command.splitlines()[-1])[-1])
                        store = run.parent / ".sessions" / run.name / ".gemini/antigravity-cli/cache"
                        self.assertTrue(json.loads((store / "onboarding.json").read_text())["onboardingComplete"])

    def test_unknown_names_fail_before_creating_runs_or_resetting_auth(self):
        for agent in (*UNKNOWN_AGENTS, "unknown"):
            marker = self.home / ".agentrun/auth" / agent / "keep"
            marker.parent.mkdir(parents=True)
            marker.write_text("existing user state")
            auth = tuple(("auth", action) for action in ("login", "import", "status", "reset"))
            for prefix in (("dry-run", "assist"), ("experiment",), ("smoke-test",), ("doctor",), *auth):
                with self.subTest(agent=agent, command=prefix):
                    result = self.run_cli(*prefix, "--agent", agent)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("知らないエージェントです:", result.stderr)
                    self.assertFalse((self.root / ".agent-runs").exists())
                    self.assertTrue(marker.exists())
            result = subprocess.run(["bash", str(ROOT / "runtime/agentrun/install-agent.sh"), agent,
                                     str(self.root / "run"), str(self.root / "cache")],
                                    env=self.env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.root / "run").exists())
        result = self.run_cli("sync-antigravity", "extra")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_removed_review_modes_and_options_are_rejected(self):
        for mode in ("review", "multi-review"):
            with self.subTest(mode=mode):
                self.assertEqual(self.run_cli(mode, "task").returncode, 2)
                self.assertEqual(self.run_cli("dry-run", mode, "task").returncode, 2)
        for flag in ("--agents", "--reviewers", "--target-diff", "--target-report"):
            with self.subTest(flag=flag):
                result = self.run_cli("dry-run", "experiment", flag, "codex", "task")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("知らないオプションです", result.stderr)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_auth_all_and_doctor_all_visit_only_supported_agents(self):
        for action, helper, expected in (("login", "_auth_login_agent", list(AGENTS)),
                                         ("import", "_auth_import_agent", list(AGENTS))):
            result = self.source(f'{helper}() {{ printf "%s\\n" "$1"; }}; auth_sync_running() {{ :; }}; '
                                 f'command_auth {action} --all')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), expected)
        result = self.run_cli("auth", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if not line.startswith(" ")],
                         ["codex:", "claude:", "antigravity:"])
        result = self.source('check_agent_auth() { printf "VISITED=%s\\n" "$1"; }; command_doctor --all')
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("VISITED=")],
                         ["VISITED=" + agent for agent in AGENTS])

    def test_antigravity_credentials_are_imported_and_staged(self):
        token = self.home / ".gemini/antigravity-cli/antigravity-oauth-token"
        token.parent.mkdir(parents=True)
        token.write_text("opaque-token")
        (token.parent / "installation_id").write_text("install-id")
        result = self.run_cli("auth", "import", "--agent", "antigravity")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        store = self.home / ".agentrun/auth/antigravity/.gemini/antigravity-cli"
        self.assertEqual((store / "antigravity-oauth-token").read_text(), "opaque-token")
        self.assertEqual((store / "installation_id").stat().st_mode & 0o777, 0o600)
        self.assertIn("store:present", self.run_cli("auth", "status", "--agent", "antigravity").stdout)
        token.write_text("host-token")  # the store takes precedence over the host copy
        run = self.root / "run"
        result = self.source('copy_auth_credentials "$1" claude', run)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((run / "home/.gemini/antigravity-cli/antigravity-oauth-token").read_text(), "opaque-token")
        self.assertEqual((run / "home/.gemini/antigravity-cli/installation_id").read_text(), "install-id")

    def fake_squeue(self, *jobs):
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        squeue = bin_dir / "squeue"
        squeue.write_text("#!/bin/sh\nprintf '%s\\n' " + " ".join(shlex.quote(job) for job in jobs) + "\n")
        squeue.chmod(0o755)
        self.env["PATH"] = f"{bin_dir}:{self.env['PATH']}"

    def make_run(self, parent, name, job, reviewer=False, finished=False):
        run = parent / ".agent-runs" / name
        (run / "live").mkdir(parents=True)
        (run / "live/slurm_job_id.txt").write_text(job + "\n")
        (run / "home/.codex").mkdir(parents=True)
        (run / "home/.codex/auth.json").write_text('{"token":"expired"}')
        if reviewer:
            (run / "home/.reviewer/codex/.codex").mkdir(parents=True)
            (run / "home/.reviewer/codex/.codex/auth.json").write_text('{"token":"expired"}')
        if finished:
            (run / "live/session_finished.txt").write_text("done\n")
        return run

    def test_login_and_import_update_running_sessions(self):
        other = self.root / "other project"
        registered = self.make_run(self.root / "elsewhere", "overlap-run", "77", reviewer=True)
        found = self.make_run(other, "launched-before-update", "42", reviewer=True)
        here = self.make_run(self.root, "current-dir", "42")
        idle = self.make_run(self.root, "job-ended", "99")
        finished = self.make_run(other, "finished", "42", finished=True)
        self.fake_squeue(f"42|{other}", "77|/nonexistent")
        result = self.source('copy_auth_credentials "$1" claude', registered)
        self.assertEqual(result.returncode, 0, result.stderr)
        (self.home / ".codex").mkdir()
        (self.home / ".codex/auth.json").write_text('{"token":"fresh"}')
        result = self.run_cli("auth", "import", "--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for run in (registered, found, here):
            self.assertEqual((run / "home/.codex/auth.json").read_text(), '{"token":"fresh"}', run)
            self.assertEqual((run / "home/.codex/auth.json").stat().st_mode & 0o777, 0o600)
        for run in (registered, found):
            self.assertEqual((run / "home/.reviewer/codex/.codex/auth.json").read_text(), '{"token":"fresh"}')
            self.assertIn(f"[SYNCED] codex -> {run.resolve()} (worker HOME, reviewer HOME)", result.stdout)
        for run in (idle, finished):
            self.assertEqual((run / "home/.codex/auth.json").read_text(), '{"token":"expired"}', run)
        # Login reuses the same path after the CLI writes host credentials.
        (self.home / ".codex/auth.json").write_text('{"token":"relogin"}')
        result = self.source('codex() { :; }; command_auth login --agent codex')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((found / "home/.reviewer/codex/.codex/auth.json").read_text(), '{"token":"relogin"}')

    def test_session_sync_without_slurm_needs_explicit_run_and_stays_in_home(self):
        run = self.make_run(self.root, "explicit", "5")
        outside = self.root / "outside"
        outside.mkdir()
        shutil.rmtree(run / "home/.codex")
        (run / "home/.codex").symlink_to(outside)  # planted from inside the capsule
        (self.home / ".codex").mkdir()
        (self.home / ".codex/auth.json").write_text('{"token":"fresh"}')
        self.env["PATH"] = "/usr/bin:/bin"
        result = self.run_cli("auth", "import", "--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("更新する実行中のセッションはありません", result.stdout)
        result = self.run_cli("auth", "import", "--agent", "codex", "--run", run)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("refusing a redirected credential path", result.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        (run / "home/.codex").unlink()
        result = self.run_cli("auth", "import", "--agent", "codex", "--run", run)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((run / "home/.codex/auth.json").read_text(), '{"token":"fresh"}')

    @unittest.skipUnless(shutil.which("jq"), "jq is required for skill synchronization")
    def test_local_and_git_skill_install_syncs_every_agent(self):
        capsule = self.root / "capsule"
        shutil.copytree(ROOT, capsule, symlinks=True,
                        ignore=shutil.ignore_patterns(".agent-runs", "__pycache__", "*.sif", "secrets"))
        source = self.root / "source.git"
        skill = source / "skills/regression-example"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: regression-example\ndescription: Test fixture.\n---\n")
        for command in (["git", "init", "-q", str(source)], ["git", "-C", str(source), "add", "."],
                        ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                         "commit", "-qm", "Add skill fixture"]):
            result = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
        for location in (str(source), source.as_uri()):
            with self.subTest(source=location):
                result = self.run_cli("skill-install", location, "--force",
                                      launcher=capsule / "runtime/agentrun/agentrun")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual({p.name for p in (capsule / "agents").iterdir()}, set(AGENTS))
                for agent in AGENTS:
                    self.assertTrue((capsule / "agents" / agent / "skills/regression-example/SKILL.md").is_file())

    def test_git_push_is_allowed_by_every_agent_and_shared_hook(self):
        for filename in ("settings.json", "settings.assist.json", "settings.experiment.json"):
            settings = json.loads((ROOT / "agents/claude" / filename).read_text())
            self.assertNotIn("Bash(git push *)", settings["permissions"]["deny"])
            settings = json.loads((ROOT / "agents/antigravity" / filename).read_text())
            self.assertFalse(any(rule.startswith("command(git push") for rule in settings["permissions"]["deny"]))
        for tool in ("Bash", "exec_command"):
            result = subprocess.run(["python3", str(ROOT / "common/hooks/git_branch_guard.py")],
                                    input=json.dumps({"tool_name": tool, "tool_input": {"command": "git push origin main"}}),
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for command in ("git push --force-with-lease origin main", "git push -f origin main", "git fetch origin",
                            "git pull origin main", "git merge feature"):
                result = subprocess.run(["python3", str(ROOT / "common/hooks/git_branch_guard.py")],
                                        input=json.dumps({"tool_name": tool, "tool_input": {"command": command}}),
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 0, command + result.stdout + result.stderr)

    def test_shared_hooks_still_block_commands_and_secret_files(self):
        for tool in ("Bash", "exec_command"):
            for hook, command, allocation in (
                ("block_dangerous_command", "rm -rf /", "1"),
                ("check_pip_forbidden", "pip install example", "1"),
                ("check_sbatch_forbidden", "sbatch train.sbatch", "1"),
                ("check_login_node", "python train.py", ""),
                ("git_branch_guard", "git rebase main", "1"),
            ):
                with self.subTest(tool=tool, hook=hook):
                    for value, expected in ((command, 2), ("git status", 0)):
                        result = subprocess.run(["python3", str(ROOT / f"common/hooks/{hook}.py")],
                                                input=json.dumps({"tool_name": tool, "tool_input": {"command": value}}),
                                                env=dict(self.env, SLURM_JOB_ID=allocation), capture_output=True, text=True, timeout=5)
                        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                        if expected:
                            self.assertEqual(json.loads(result.stdout)["decision"], "block")
        for tool, payload in (("Read", {"file_path": "/home/sandbox/.codex/auth.json"}),
                              ("apply_patch", {"command": "*** Begin Patch\n*** Add File: secrets/token\n+value\n*** End Patch"})):
            result = subprocess.run(["python3", str(ROOT / "common/hooks/block_dangerous_command.py")],
                                    input=json.dumps({"tool_name": tool, "tool_input": payload}),
                                    env=self.env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def antigravity_hook(self, event, hook, payload, role="worker"):
        return subprocess.run(["python3", str(ROOT / "common/hooks/worker_hook.py"), "--antigravity", event,
                               str(ROOT / f"common/hooks/{hook}.py")], input=json.dumps(payload),
                              env=dict(self.env, SLURM_JOB_ID="1", AGENTRUN_ROLE=role, AGENTRUN_DIR=str(self.root / "runs")),
                              capture_output=True, text=True, timeout=10)

    def test_antigravity_hooks_reach_the_shared_hooks_and_answer_in_its_format(self):
        # Payloads as agy 1.5 sends them: camelCase, toolCall.name/args, "Path" for files.
        def call(name, **args):
            return {"conversationId": "c1", "hookEventName": "PreToolUse", "cwd": "/workspace",
                    "toolCall": {"id": "t1", "name": name, "args": args}}
        for hook, payload in (("block_dangerous_command", call("run_command", CommandLine="sudo ls")),
                              ("block_dangerous_command", call("read_file", Path="/home/sandbox/.codex/auth.json")),
                              ("block_dangerous_command", call("write_file", Path="/workspace/.env", Content="x")),
                              ("check_pip_forbidden", call("run_command", CommandLine="pip install requests")),
                              ("check_sbatch_forbidden", call("run_command", CommandLine="sbatch job.sh"))):
            with self.subTest(hook=hook, payload=payload["toolCall"]):
                result = self.antigravity_hook("PreToolUse", hook, payload)
                self.assertEqual(result.returncode, 0, result.stderr)
                answer = json.loads(result.stdout)
                self.assertEqual(answer["decision"], "deny")
                self.assertTrue(answer["reason"])
        for hook, payload in (("block_dangerous_command", call("run_command", CommandLine="git status")),
                              ("block_dangerous_command", call("read_file", Path="/workspace/calc.py")),
                              ("check_pip_forbidden", call("run_command", CommandLine="uv run python x.py"))):
            with self.subTest(hook=hook, allowed=payload["toolCall"]):
                result = self.antigravity_hook("PreToolUse", hook, payload)
                self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        # PostToolUse records the command like the other agents' Bash calls; Stop only observes.
        result = self.antigravity_hook("PostToolUse", "update_run_status", call("run_command", CommandLine="ls -la"))
        self.assertEqual(json.loads(result.stdout), {})
        event = json.loads((self.root / "runs/live/command_log.jsonl").read_text().splitlines()[-1])
        self.assertEqual((event["tool"], event["command"]), ("Bash", "ls -la"))
        # Stop: session_log.py holds a normal finish once ("continue" in agy's terms), then lets it stop.
        stop = {"hookEventName": "Stop", "fullyIdle": True, "terminationReason": "NO_TOOL_CALL"}
        answer = json.loads(self.antigravity_hook("Stop", "session_log", stop).stdout)
        self.assertEqual(answer["decision"], "continue")
        self.assertIn("live/session_log.md", answer["reason"])
        for done in ({**stop, "continuationActive": True}, {**stop, "terminationReason": "USER_CANCELED"}):
            self.assertEqual(json.loads(self.antigravity_hook("Stop", "session_log", done).stdout), {})
        # In the reviewer role the worker hooks stay inert, answering without running.
        result = self.antigravity_hook("PreToolUse", "block_dangerous_command",
                                       call("run_command", CommandLine="sudo ls"), role="reviewer")
        self.assertEqual(json.loads(result.stdout), {"decision": "allow"})
        result = self.antigravity_hook("Wrong", "block_dangerous_command", {})
        self.assertNotEqual(result.returncode, 0)

    def run_hook(self, name, payload, **env):
        return subprocess.run(["python3", str(ROOT / f"common/hooks/{name}.py")], input=json.dumps(payload),
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=30)

    def test_file_changes_are_recorded_however_files_are_edited(self):
        workspace, runs = self.root / "workspace", self.root / "runs"
        workspace.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(workspace), *args], check=True)
        (workspace / "train.py").write_text("a = 1\nb = 2\nc = 3\n")
        (workspace / "old.txt").write_text("keep\n")
        (workspace / ".gitignore").write_text("outputs/\n")
        subprocess.run(["git", "-C", str(workspace), "add", "."], check=True)
        subprocess.run(["git", "-C", str(workspace), "commit", "-qm", "base"], check=True)
        env = {"AGENTRUN_DIR": str(runs), "AGENTRUN_WORKSPACE": str(workspace)}
        bash = {"tool_name": "Bash", "tool_input": {"command": "sed -i ..."}}

        def record():
            result = self.run_hook("record_file_changes", bash, **env)
            self.assertEqual((result.returncode, result.stdout), (0, ""), result.stderr)  # nothing reaches the agent
            log = runs / "live/events.jsonl"
            lines = log.read_text().splitlines() if log.exists() else []
            for line in lines:
                self.assertTrue(json.loads(line)["ts"].endswith("+09:00"), line)  # Japan time, like the other logs
            log.unlink(missing_ok=True)
            return {e["file"]: {k: v for k, v in e.items() if k not in ("ts", "event", "file")}
                    for e in map(json.loads, lines)}

        # A shell edit (as sed -i would do) is measured against HEAD the first time.
        (workspace / "train.py").write_text("a = 1\nb = 20\nc = 3\nd = 4\n")
        self.assertEqual(record(), {"train.py": {"added": 2, "removed": 1}})
        self.assertEqual(record(), {})  # nothing changed since
        # The next change counts against the last one, not against HEAD.
        (workspace / "train.py").write_text("a = 1\nb = 20\nc = 3\nd = 4\ne = 5\n")
        self.assertEqual(record(), {"train.py": {"added": 1, "removed": 0}})
        (workspace / "new.py").write_text("x\ny\n")
        (workspace / "blob.bin").write_bytes(b"\0\1\2")
        (workspace / "old.txt").unlink()
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__/train.cpython-312.pyc").write_bytes(b"\0bytecode")
        (workspace / "outputs").mkdir()
        (workspace / "outputs/ignored.txt").write_text("not tracked\n")
        self.assertEqual(record(), {"new.py": {"added": 2, "removed": 0, "created": True},
                                    "blob.bin": {"binary": True, "created": True},
                                    "old.txt": {"added": 0, "removed": 1, "deleted": True}})
        # Going back to HEAD (git checkout) is a change too, and then nothing is kept.
        subprocess.run(["git", "-C", str(workspace), "checkout", "--", "train.py"], check=True)
        self.assertEqual(record(), {"train.py": {"added": 1, "removed": 3}})  # b = 20 -> b = 2, d and e gone
        self.assertEqual(record(), {})
        # Outside a Git repository nothing is compared or written.
        plain = self.root / "plain"
        plain.mkdir()
        result = self.run_hook("record_file_changes", bash, AGENTRUN_DIR=str(runs), AGENTRUN_WORKSPACE=str(plain))
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse((runs / "live/events.jsonl").exists())

    def test_session_log_asks_for_one_line_per_stop_and_notifies_once(self):
        for payload in ({"hook_event_name": "Stop", "session_id": "s", "stop_hook_active": False},  # Claude Code
                        {"hook_event_name": "Stop", "turn_id": "t", "model": "m", "stop_hook_active": False}):  # Codex
            result = self.run_hook("session_log", payload, AGENTRUN_TIMEZONE="Asia/Tokyo")
            answer = json.loads(result.stdout)
            self.assertEqual(answer["decision"], "block")
            self.assertRegex(answer["reason"], r"/runs/live/session_log\.md .*`- \d{4}-\d{2}-\d{2} \d{2}:\d{2} <")
            self.assertLess(len(answer["reason"]), 320)  # a short instruction keeps the extra turn cheap
            self.assertIn("exactly `.`", answer["reason"])  # a fixed final message, not a repeated answer
            # Once the agent wrote the line and stops again, it is let go.
            result = self.run_hook("session_log", dict(payload, stop_hook_active=True))
            self.assertEqual((result.returncode, result.stdout), (0, ""))
        # agy: one line per user turn, even when another Stop hook stops it again in that turn.
        runs = self.root / "runs"
        transcript = self.root / "agy-transcript.jsonl"
        transcript.write_text('{"type": "USER_INPUT"}\n{"type": "PLANNER_RESPONSE", "content": "x"}\n')
        stop = {"hookEventName": "Stop", "terminationReason": "NO_TOOL_CALL", "conversationId": "c1",
                "transcriptPath": str(transcript)}

        def agy_stop():
            result = subprocess.run(["python3", str(ROOT / "common/hooks/worker_hook.py"), "--antigravity", "Stop",
                                     str(ROOT / "common/hooks/session_log.py")], input=json.dumps(stop),
                                    env=dict(self.env, AGENTRUN_DIR=str(runs)), capture_output=True, text=True, timeout=10)
            return json.loads(result.stdout).get("decision")
        self.assertEqual(agy_stop(), "continue")
        self.assertIsNone(agy_stop())  # same turn: no second line
        with transcript.open("a") as stream:
            stream.write('{"type": "USER_INPUT"}\n')  # the person asks something new
        self.assertEqual(agy_stop(), "continue")
        spec = importlib.util.spec_from_file_location("stop_notify", ROOT / "common/hooks/stop_notify.py")
        notify = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(notify)
        notify.SLACK_WEBHOOK_URL = "https://hooks.example.invalid/agentrun"
        sent = []
        import io, urllib.request
        from unittest import mock
        for active in (False, True):
            with mock.patch.object(urllib.request, "urlopen", lambda request, timeout: sent.append(request)), \
                    mock.patch("sys.stdin", io.StringIO(json.dumps({"stop_hook_active": active,
                                                                    "last_assistant_message": "done"}))):
                self.assertEqual(notify.main(), 0)
        self.assertEqual(len(sent), 1)  # the stop after the log line does not notify again

    def test_antigravity_stop_summary_is_its_last_reply(self):
        def load(name):
            spec = importlib.util.spec_from_file_location(name, ROOT / f"common/hooks/{name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        worker_hook, stop_notify = load("worker_hook"), load("stop_notify")
        transcript = self.root / "transcript_full.jsonl"
        steps = [{"type": "USER_INPUT", "content": "<USER_REQUEST>\n直して\n</USER_REQUEST>"},
                 {"type": "PLANNER_RESPONSE", "content": "途中経過です"},
                 {"type": "PLANNER_RESPONSE", "content": "calc.py を直しました。\nテストも通りました。"},
                 {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "run_command"}]},
                 {"type": "GENERIC", "content": "tool output"}]
        # The last line may still be being written when the hook runs.
        transcript.write_text("".join(json.dumps(step, ensure_ascii=False) + "\n" for step in steps) + '{"type": "PLANN')
        payload = worker_hook.translate({"hookEventName": "Stop", "transcriptPath": str(transcript)})
        self.assertEqual(payload["last_assistant_message"], "calc.py を直しました。\nテストも通りました。")
        self.assertEqual(stop_notify.detect_agent(payload), "Antigravity")
        self.assertEqual(stop_notify.extract_summary(payload), "calc.py を直しました。 テストも通りました。")
        # Without a readable log the notification falls back to the generic text, as before.
        missing = worker_hook.translate({"hookEventName": "Stop", "transcriptPath": str(self.root / "none")})
        self.assertEqual(stop_notify.extract_summary(missing), "作業が完了しました。")
        self.assertNotIn("last_assistant_message", worker_hook.translate({"hookEventName": "PreToolUse"}))

    def test_antigravity_hook_matchers_cover_its_tool_names(self):
        manifest = json.loads((ROOT / "agents/antigravity/hooks.manifest.json").read_text())
        def scripts(event, tool):
            return [entry["script"] for group in manifest["hooks"] if group["event"] == event
                    and any(tool == name for name in group["matcher"].split("|"))
                    for entry in group["entries"]]
        claude = json.loads((ROOT / "agents/claude/hooks.manifest.json").read_text())
        bash = [entry["script"] for group in claude["hooks"] if group["matcher"] == "Bash"
                and group["event"] == "PreToolUse" for entry in group["entries"]]
        self.assertEqual(scripts("PreToolUse", "run_command"), bash)
        for tool in ("read_file", "write_file", "edit_file"):
            self.assertIn("block_dangerous_command.py", scripts("PreToolUse", tool))
        for tool in ("write_file", "edit_file"):
            self.assertIn("record_file_changes.py", scripts("PostToolUse", tool))
        # Shell commands can edit files too (sed -i, redirects), so the recorder runs after them as well.
        self.assertIn("record_file_changes.py", scripts("PostToolUse", "run_command"))
        generated = json.loads((ROOT / "agents/antigravity/hooks.json").read_text())["agentrun"]
        self.assertEqual(sorted(generated), ["PostToolUse", "PreToolUse", "Stop"])
        self.assertTrue(all("worker_hook.py --antigravity Stop " in h["command"] for h in generated["Stop"]))

    def test_command_events_exclude_tool_results_and_stop_summaries_keep_every_agent(self):
        for name in ("update_run_status", "stop_notify"):
            spec = importlib.util.spec_from_file_location(name, ROOT / f"common/hooks/{name}.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if name == "update_run_status":
                for tool in ("Bash", "exec_command"):
                    fields = module.command_fields(json.dumps({"tool_name": tool,
                        "tool_input": {"command": "git status"}, "tool_response": "private output"}))
                    self.assertEqual(fields, {"tool": tool, "command": "git status"})
            else:
                for payload, agent in (({"session_id": "fixture"}, "Claude Code"), ({"turn_id": "fixture"}, "Codex"),
                                       ({"session_id": "fixture", "agent": "antigravity"}, "Antigravity")):
                    self.assertEqual(module.detect_agent(payload), agent)
                    self.assertEqual(module.extract_summary(dict(payload, last_assistant_message="Work\nfinished")),
                                     "Work finished")


if __name__ == "__main__":
    unittest.main()
