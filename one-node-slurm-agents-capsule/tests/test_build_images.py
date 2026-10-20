"""Exercise image rebuild decisions with a local mock of Apptainer."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


BUILD_DIR = Path(__file__).resolve().parents[1] / "runtime/apptainer"


class BuildImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrun build with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("build-images.sh", "base-system.def"):
            shutil.copy2(BUILD_DIR / name, self.root / name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        mock = self.bin / "apptainer"
        mock.write_text('''#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$4" >> "$TEST_BUILD_CALLS"
printf 'new image' > "$3"
if [ "$4" = "${TEST_BUILD_FAIL:-}" ]; then exit 23; fi
''')
        mock.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        SLURM_JOB_ID="local-test", TEST_BUILD_CALLS=str(self.root / "calls"))
        self.env.pop("TEST_BUILD_FAIL", None)
        self.seed("base-system.def", 100)

    def seed(self, name, timestamp):
        path = self.root / name
        path.write_text("old image" if name.endswith(".sif") else "definition")
        os.utime(path, (timestamp, timestamp))

    def fresh_image(self):
        self.seed("base-system.sif", 200)

    def run_build(self, *args, expected=0):
        result = subprocess.run(["bash", str(self.root / "build-images.sh"), *args],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def calls(self):
        log = self.root / "calls"
        return log.read_text().splitlines() if log.exists() else []

    def test_build_missing_image(self):
        self.run_build("--run")
        self.assertEqual(self.calls(), ["base-system.def"])
        self.assertEqual((self.root / "base-system.sif").read_text(), "new image")
        self.assertEqual(list(self.root.glob("*.sif")), [self.root / "base-system.sif"])

    def test_reuse_fresh_image(self):
        self.fresh_image()
        self.run_build("--run")
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.root / "base-system.sif").read_text(), "old image")

    def test_definition_change_rebuilds_system(self):
        self.fresh_image()
        self.seed("base-system.def", 400)
        self.run_build("--run")
        self.assertEqual(self.calls(), ["base-system.def"])

    def test_equal_timestamp_rebuilds_system(self):
        self.fresh_image()
        self.seed("base-system.def", 200)
        self.run_build("--run")
        self.assertEqual(self.calls(), ["base-system.def"])

    def test_force_fresh_image(self):
        self.fresh_image()
        self.run_build("--run", "--force")
        self.assertEqual(self.calls(), ["base-system.def"])
        self.assertEqual((self.root / "base-system.sif").read_text(), "new image")

    def test_force_removes_obsolete_agent_image_after_success(self):
        self.fresh_image()
        self.seed("base-agent.sif", 500)
        result = self.run_build("--run", "--force")
        self.assertFalse((self.root / "base-agent.sif").exists())
        self.assertEqual((self.root / "base-system.sif").read_text(), "new image")
        self.assertIn("removed obsolete", result.stdout)

    def test_force_removes_obsolete_symlink_without_deleting_target(self):
        self.seed("old-image.sif", 500)
        (self.root / "base-agent.sif").symlink_to("old-image.sif")
        self.run_build("--run", "--force")
        self.assertFalse((self.root / "base-agent.sif").is_symlink())
        self.assertEqual((self.root / "old-image.sif").read_text(), "old image")

    def test_legacy_targets_build_single_image(self):
        for target in ("system", "all", "agent"):
            with self.subTest(target=target):
                (self.root / "calls").unlink(missing_ok=True)
                self.fresh_image()
                result = self.run_build(target, "--force", "--run")
                self.assertEqual(self.calls(), ["base-system.def"])
                self.assertEqual(list(self.root.glob("*.sif")), [self.root / "base-system.sif"])
                if target == "agent":
                    self.assertIn("warning:", result.stderr)
                    self.assertIn("base-system.sif", result.stderr)

    def test_obsolete_agent_image_is_unused_and_preserved(self):
        self.seed("base-agent.sif", 500)
        self.run_build("--run", "agent")
        self.assertEqual(self.calls(), ["base-system.def"])
        self.assertEqual((self.root / "base-agent.sif").read_text(), "old image")

    def test_force_still_requires_run(self):
        self.fresh_image()
        self.seed("base-agent.sif", 500)
        result = self.run_build("--force")
        self.assertIn("dry-run", result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertEqual((self.root / "base-system.sif").read_text(), "old image")
        self.assertEqual((self.root / "base-agent.sif").read_text(), "old image")

    def test_unknown_argument_is_rejected(self):
        self.run_build("--run", "--froce", expected=2)
        self.assertEqual(self.calls(), [])

    def test_build_requires_slurm_allocation(self):
        self.env.pop("SLURM_JOB_ID")
        self.run_build("--run", "--force", expected=2)
        self.assertEqual(self.calls(), [])

    def test_failed_build_preserves_image_and_cleans_partial_image(self):
        self.fresh_image()
        self.seed("base-agent.sif", 500)
        self.env["TEST_BUILD_FAIL"] = "base-system.def"
        self.run_build("--run", "--force", expected=23)
        self.assertEqual(self.calls(), ["base-system.def"])
        self.assertEqual((self.root / "base-system.sif").read_text(), "old image")
        self.assertEqual((self.root / "base-agent.sif").read_text(), "old image")
        self.assertEqual(sorted(self.root.glob("*.sif")), [self.root / "base-agent.sif", self.root / "base-system.sif"])

    def test_failed_first_build_leaves_no_image(self):
        self.env["TEST_BUILD_FAIL"] = "base-system.def"
        self.run_build("--run", expected=23)
        self.assertEqual(self.calls(), ["base-system.def"])
        self.assertEqual(list(self.root.glob("*.sif")), [])


if __name__ == "__main__":
    unittest.main()
