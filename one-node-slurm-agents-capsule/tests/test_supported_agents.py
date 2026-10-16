"""Exercise the supported agent boundary without Slurm, network, or real credentials."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
RETIRED_AGENTS = ("antigravity", "agy", "gemini")


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
        self.assertEqual([line.split()[0] for line in result.stdout.splitlines()[1:]], ["codex", "claude"])
        result = self.run_cli("dry-run", "assist", "--no-secrets")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("selected_agent: codex", result.stdout)
        self.assertFalse((self.root / ".agent-runs").exists())

    def test_both_agents_prepare_every_profile_with_shared_assets(self):
        for agent in ("codex", "claude"):
            for mode in ("assist", "experiment", "campaign", "review", "multi-review"):
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
                    self.assertEqual({p.name for p in (run / "reviews").glob("*.md")},
                                     {"claude.md", "codex.md", "summary.md", "final_recommendation.md"})
                    for retired in RETIRED_AGENTS:
                        self.assertNotIn(retired, command)
                        self.assertFalse(any(retired in str(p.relative_to(run)) for p in run.rglob("*")))

    def test_removed_names_fail_before_creating_runs_or_resetting_auth(self):
        for agent in (*RETIRED_AGENTS, "unknown"):
            marker = self.home / ".agentrun/auth" / agent / "keep"
            marker.parent.mkdir(parents=True)
            marker.write_text("existing user state")
            for prefix in (("dry-run", "assist"), ("experiment",), ("smoke-test",), ("doctor",),
                           *(("auth", action) for action in ("login", "import", "status", "reset"))):
                with self.subTest(agent=agent, command=prefix):
                    result = self.run_cli(*prefix, "--agent", agent)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("unknown agent:", result.stderr)
                    self.assertFalse((self.root / ".agent-runs").exists())
                    self.assertTrue(marker.exists())
            result = subprocess.run(["bash", str(ROOT / "runtime/agentrun/install-agent.sh"), agent,
                                     str(self.root / "run"), str(self.root / "cache")],
                                    env=self.env, text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((self.root / "run").exists())
        result = self.run_cli("sync-antigravity")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_reviewer_lists_reject_unsupported_names(self):
        for flag in ("--agents", "--reviewers"):
            for value in (*RETIRED_AGENTS, "claude,antigravity", "codex,", ",claude"):
                with self.subTest(flag=flag, value=value):
                    result = self.run_cli("dry-run", "multi-review", flag, value, "task")
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            result = self.run_cli("dry-run", "multi-review", flag, "codex,claude", "task")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_auth_all_and_doctor_all_visit_only_supported_agents(self):
        for action, helper in (("login", "_auth_login_agent"), ("import", "_auth_import_agent")):
            result = self.source(f'{helper}() {{ printf "%s\\n" "$1"; }}; command_auth {action} --all')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["codex", "claude"])
        result = self.run_cli("auth", "status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if not line.startswith(" ")],
                         ["codex:", "claude:"])
        result = self.source('check_agent_auth() { printf "VISITED=%s\\n" "$1"; }; command_doctor --all')
        self.assertIn(result.returncode, (0, 1), result.stderr)
        self.assertEqual([line for line in result.stdout.splitlines() if line.startswith("VISITED=")],
                         ["VISITED=codex", "VISITED=claude"])

    @unittest.skipUnless(shutil.which("jq"), "jq is required for skill synchronization")
    def test_local_and_git_skill_install_sync_only_supported_agents(self):
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
                self.assertEqual({p.name for p in (capsule / "agents").iterdir()}, {"codex", "claude"})
                for agent in ("codex", "claude"):
                    self.assertTrue((capsule / "agents" / agent / "skills/regression-example/SKILL.md").is_file())

    def test_shared_hooks_still_block_commands_and_secret_files(self):
        for tool in ("Bash", "exec_command"):
            for hook, command, allocation in (
                ("block_dangerous_command", "rm -rf /", "1"),
                ("check_pip_forbidden", "pip install example", "1"),
                ("check_sbatch_forbidden", "sbatch train.sbatch", "1"),
                ("check_login_node", "python train.py", ""),
                ("git_branch_guard", "git push", "1"),
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

    def test_command_events_exclude_tool_results_and_stop_summaries_keep_both_agents(self):
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
                for payload, agent in (({"session_id": "fixture"}, "Claude Code"), ({"turn_id": "fixture"}, "Codex")):
                    self.assertEqual(module.detect_agent(payload), agent)
                    self.assertEqual(module.extract_summary(dict(payload, last_assistant_message="Work\nfinished")),
                                     "Work finished")


if __name__ == "__main__":
    unittest.main()
