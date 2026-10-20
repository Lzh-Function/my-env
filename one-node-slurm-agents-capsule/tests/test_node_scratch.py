"""Check optional node-local mounts without requiring Slurm or a host /scratch."""

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
HELPER = ROOT / "runtime/agentrun/node-scratch.sh"


class NodeScratchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="node scratch with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(os.environ, HOME=str(self.root / "home"))
        Path(self.env["HOME"]).mkdir()

    def shell(self, script, *args):
        result = subprocess.run(
            ["bash", "-c", "set -euo pipefail; " + script, "bash", *map(str, args)],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def mount_args(self, path):
        result = self.shell(
            'source "$1"; _agentrun_node_scratch_setup "$2"; '
            'printf "%s\\0" "${AGENTRUN_NODE_SCRATCH_ARGS[@]}"',
            HELPER,
            path,
        )
        return result.stdout.rstrip("\0").split("\0")

    def test_directory_is_mounted_read_write_without_changing_its_contents(self):
        path = self.root / "SSD 'quoted' $(literal)"
        path.mkdir()
        (path / "keep").write_text("existing user data")
        self.assertEqual(
            self.mount_args(path),
            [
                "--bind",
                f"{path}:/node-scratch:rw",
                "--env",
                "AGENTRUN_NODE_SCRATCH=/node-scratch",
            ],
        )
        self.assertEqual(list(path.iterdir()), [path / "keep"])
        self.assertEqual((path / "keep").read_text(), "existing user data")

    def test_missing_directory_and_regular_file_are_not_mounted_or_created(self):
        path = self.root / "SSD"
        for is_file in (False, True):
            with self.subTest(is_file=is_file):
                if is_file:
                    path.write_text("not a directory")
                self.assertEqual(
                    self.mount_args(path), ["--env", "AGENTRUN_NODE_SCRATCH="]
                )
                self.assertEqual(path.exists(), is_file)

    def test_availability_is_checked_again_for_each_execution(self):
        path = self.root / "SSD"
        self.assertNotIn("--bind", self.mount_args(path))
        path.mkdir()
        self.assertIn("--bind", self.mount_args(path))
        path.rmdir()
        self.assertNotIn("--bind", self.mount_args(path))

    def test_generated_launch_freezes_submit_user_and_keeps_run_scratch_separate(self):
        for agent in ("codex", "claude"):
            for launch in ("interactive", "batch"):
                with self.subTest(agent=agent, launch=launch):
                    run = self.root / f"{agent}-{launch}"
                    self.shell(
                        'source "$1"; id() { printf "submission-user\\n"; }; '
                        "parse_run_args --no-secrets --no-gh-broker; "
                        'write_plan assist "$2" "$PWD" "" 0 00:10:00 task "$3" "" "$4"',
                        LAUNCHER,
                        agent,
                        run,
                        launch,
                    )
                    script = (run / "apptainer_exec.sh").read_text()
                    setup = "_agentrun_node_scratch_setup /scratch/submission-user"
                    self.assertIn(setup, script)
                    # Substitute only the source path to simulate a node-local SSD
                    # that was unavailable while preparing the job above.
                    path = self.root / f"SSD {agent}-{launch}"
                    script = script.replace(
                        setup, f"_agentrun_node_scratch_setup {shlex.quote(str(path))}"
                    )
                    fake = "apptainer() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' \"$@\"; };\n"
                    for available in (False, True):
                        if available:
                            path.mkdir()
                        result = self.shell(fake + script)
                        args = json.loads(result.stdout)
                        self.assertIn(f"{run}/scratch:/scratch:rw", args)
                        self.assertEqual(f"{path}:/node-scratch:rw" in args, available)
                        self.assertIn(
                            "AGENTRUN_NODE_SCRATCH="
                            + ("/node-scratch" if available else ""),
                            args,
                        )


if __name__ == "__main__":
    unittest.main()
