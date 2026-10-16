"""Check declared outputs, generated instructions, and completed run verification."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
MODES = ("assist", "experiment", "campaign", "review", "multi-review")


def declared_outputs(mode):
    profile = (ROOT / "profiles" / f"{mode}.yaml").read_text()
    required = profile.split("  required:\n", 1)[1].split("policy:", 1)[0]
    return [line.strip().removeprefix("- ") for line in required.splitlines() if line.strip()]


class RunContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="run contract with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call(self, function, *args):
        return subprocess.run(
            ["bash", "-c", 'source "$1"; shift; "$@"', "bash", str(LAUNCHER), function, *map(str, args)],
            cwd=self.root, env=dict(os.environ, GH_ENV_FILE=""), capture_output=True, text=True, timeout=10,
        )

    def completed_run(self, mode):
        run = self.root / mode
        for name in [*declared_outputs(mode), "capsule.yaml", "prompt.txt", "goal.yaml",
                     "live/exit_code.txt", "live/slurm_job_id.txt"]:
            path = run / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n" if path.suffix == ".json" else "")
        (run / "capsule.yaml").write_text(f"mode: {mode}\n")
        (run / "live/status.json").write_text(json.dumps({"status": "success"}))
        (run / "artifacts/report.md").write_text("Completed the requested work.\n")
        (run / "artifacts/run_title.txt").write_text("checked capsule run output contract\n")
        return run

    def test_each_profile_matches_runtime_and_generated_prompt(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                expected = declared_outputs(mode)
                result = self.call("profile_required_outputs", mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)
                prompt = self.root / f"{mode}.txt"
                result = self.call("write_prompt", prompt, mode, "codex", self.root, "test goal", "batch")
                self.assertEqual(result.returncode, 0, result.stderr)
                outputs = [line.removeprefix("- /runs/") for line in prompt.read_text().splitlines()
                           if line.startswith("- /runs/")]
                self.assertEqual(outputs, expected)

    @unittest.skipUnless(shutil.which("jq"), "jq is required for verify-run")
    def test_completed_runs_pass_in_every_mode(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                result = self.call("command_verify_run", self.completed_run(mode))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("jq"), "jq is required for verify-run")
    def test_missing_or_empty_run_title_fails(self):
        run = self.completed_run("assist")
        title = run / "artifacts/run_title.txt"
        for missing in (False, True):
            with self.subTest(missing=missing):
                title.write_text("")
                if missing:
                    title.unlink()
                result = self.call("command_verify_run", run)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("[FAIL] nonempty:artifacts/run_title.txt", result.stdout)

    @unittest.skipUnless(shutil.which("jq"), "jq is required for verify-run")
    def test_campaign_requires_its_job_proposal(self):
        run = self.completed_run("campaign")
        (run / "artifacts/proposed_train.sbatch").unlink()
        result = self.call("command_verify_run", run)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("[FAIL] profile_required:artifacts/proposed_train.sbatch", result.stdout)

    @unittest.skipUnless(shutil.which("jq"), "jq is required for verify-run")
    def test_generated_smoke_job_satisfies_the_contract(self):
        result = self.call("command_smoke_test", "--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        run = next((self.root / ".agent-runs").glob("*smoke-test*"))
        result = subprocess.run(
            ["bash", str(run / "submit.sbatch")], cwd=self.root,
            env=dict(os.environ, SLURM_JOB_ID="local-contract-test"),
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.call("command_verify_run", run)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
