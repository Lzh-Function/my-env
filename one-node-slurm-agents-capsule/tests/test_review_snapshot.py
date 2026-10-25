"""Large repositories must produce bounded, explicit partial review inputs."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime/agentrun"))
import review_snapshot as snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="review snapshot ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run = self.root / "run"
        (self.run / "artifacts").mkdir(parents=True)
        self.brief = self.run / "artifacts/brief.md"
        self.brief.write_text("Review the code changes and supplied evidence.\n")
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.repo / "code.py").write_text("value = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")

    def git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True
        )

    def capture(self, **kwargs):
        return snapshot.capture(
            self.repo,
            self.run,
            self.root / "input",
            "HEAD",
            kwargs.pop("includes", []),
            str(self.brief),
            {},
            **kwargs,
        )

    def test_22_large_tracked_images_are_omitted_without_aborting(self):
        for i in range(22):
            with (self.repo / f"figure-{i}.png").open("wb") as stream:
                stream.truncate(5 * 1024 * 1024)
        self.git("add", ".")
        result = self.capture()
        self.assertEqual(len(result["omitted"]), 22)
        self.assertTrue(all("4 MiB" in e["reason"] for e in result["omitted"]))
        self.assertIn("source/code.py", [e["path"] for e in result["files"]])
        self.assertTrue(any(e["path"].startswith("brief/") for e in result["files"]))
        self.assertFalse(list((self.root / "input/source").glob("*.png")))

    def test_explicit_large_input_reports_size_instead_of_silently_skipping(self):
        path = self.run / "artifacts/large.dat"
        with path.open("wb") as stream:
            stream.truncate(snapshot.MAX_FILE + 1)
        with self.assertRaisesRegex(snapshot.InputTooLarge, "4 MiB file size limit"):
            self.capture(includes=[str(path)])

    def test_changed_code_and_explicit_evidence_precede_unchanged_large_context(self):
        for i in range(6):
            (self.repo / f"aaa-context-{i}.txt").write_bytes(b"x" * 3000)
        self.git("add", ".")
        self.git("commit", "-qm", "context")
        (self.repo / "code.py").write_text("value = 2\n")
        evidence = self.run / "artifacts/evidence.txt"
        evidence.write_text("important evidence\n")
        with (
            patch.object(snapshot, "MAX_FILE", 4096),
            patch.object(snapshot, "MAX_TOTAL", 16000),
        ):
            result = self.capture(includes=[str(evidence)])
        files = result["files"]
        self.assertIn("source/code.py", [e["path"] for e in files])
        self.assertIn(str(evidence), [e["original"] for e in files])
        self.assertTrue(result["omitted"])
        actual = sum(
            p.stat().st_size for p in (self.root / "input").rglob("*") if p.is_file()
        )
        self.assertLessEqual(actual, 16000)

    def test_huge_old_revision_patch_is_omitted_with_a_reason(self):
        (self.repo / "code.py").write_text("old line\n" * 2000)
        self.git("add", ".")
        self.git("commit", "-qm", "large old source")
        (self.repo / "code.py").write_text("value = 2\n")
        with patch.object(snapshot, "MAX_FILE", 4096):
            result = self.capture()
        self.assertTrue(any(e["path"] == "diff.patch" for e in result["omitted"]))
        self.assertEqual((self.root / "input/diff.patch").read_bytes(), b"")

    def test_brief_text_and_missing_empty_or_non_utf8_files_are_rejected(self):
        for value in ("review\nthis", "x" * 5000, "not-a-file.md"):
            with (
                self.subTest(value=value[:20]),
                self.assertRaisesRegex(ValueError, "brief"),
            ):
                snapshot.brief_file(value, self.repo, self.run)
        for content in (b"", b"\xff"):
            self.brief.write_bytes(content)
            with self.assertRaisesRegex(ValueError, "brief"):
                snapshot.brief_file(str(self.brief), self.repo, self.run)

    def test_manifest_cannot_be_approved_by_hiding_omissions(self):
        with (self.repo / "large.dat").open("wb") as stream:
            stream.truncate(snapshot.MAX_FILE + 1)
        self.git("add", ".")
        result = self.capture()
        saved = json.loads((self.root / "input/manifest.json").read_text())
        self.assertEqual(saved["omitted"], result["omitted"])
        self.assertTrue(
            snapshot.current(
                result, (self.repo, self.run / "artifacts", self.run / "reviews")
            )
        )


if __name__ == "__main__":
    unittest.main()
