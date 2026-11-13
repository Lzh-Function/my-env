"""起動設定テンプレートの保存・読み出し・削除と --template の展開を検証する。"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_sessions import LAUNCHER, sessions


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="template repo ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "shared data"
        self.data.mkdir()
        home = self.root / "home"
        home.mkdir()
        self.store = home / ".agentrun/templates"
        self.env = dict(os.environ, HOME=str(home), AGENTRUN_SECRETS_FILE="")
        self.env.pop("AGENTRUN_TEMPLATE_DIR", None)

    def agentrun(self, *args, expected=0):
        result = subprocess.run([str(LAUNCHER), *args], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def expand(self, *args):
        script = ('source "$1"; shift; parse_run_args "$@"; '
                  'printf "%s\\n" "$AGENT" "$REPO" "$CPUS" "$MEM" "$TEMPLATE_NAME" "${EXTRA_BINDS[@]}"')
        result = subprocess.run(["bash", "-c", script, "bash", str(LAUNCHER), *args], cwd=self.root,
                                env=self.env, capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.splitlines()

    def test_save_list_show_reuse_and_delete(self):
        self.agentrun("template", "save", "gpu-a", "--agent", "codex", "--repo", ".", "--cpus", "4",
                      "--mem", "8G", "--bind", f"{self.data}:/data:ro", "--no-secrets", "--overlap", "42")
        saved = json.loads((self.store / "gpu-a.json").read_text())
        self.assertEqual((saved["mode"], saved["agent"]), ("assist", "codex"))
        self.assertNotIn("--overlap", saved["args"])
        self.assertEqual(oct((self.store / "gpu-a.json").stat().st_mode & 0o777), "0o600")
        self.assertIn("gpu-a  assist  codex", self.agentrun("template", "list").stdout)
        self.assertIn(f"--bind {self.data}:/data:ro", self.agentrun("template", "show", "gpu-a").stdout)
        # Existing names are kept unless --force is given.
        self.agentrun("template", "save", "gpu-a", "--repo", ".", expected=3)
        # Options after --template override it; binds accumulate.
        agent, repo, cpus, mem, name, *binds = self.expand("--template", "gpu-a", "--cpus", "2")
        self.assertEqual((agent, repo, cpus, mem, name), ("codex", str(self.root), "2", "8G", "gpu-a"))
        self.assertEqual(binds, [f"{self.data}:/data:ro"])
        self.agentrun("template", "save", "gpu-a", "--force", "--template", "gpu-a", "--cpus", "16", "--mode", "experiment")
        saved = json.loads((self.store / "gpu-a.json").read_text())
        self.assertEqual(saved["mode"], "experiment")
        self.assertIn("16", saved["args"])
        self.agentrun("template", "delete", "gpu-a", "--yes")
        self.assertFalse((self.store / "gpu-a.json").exists())
        self.agentrun("template", "show", "gpu-a", expected=2)

    def test_template_from_a_run_keeps_its_launch_settings(self):
        run = self.root / ".agent-runs/20261113_120000_assist_claude"
        run.mkdir(parents=True)
        sessions.init(run, "claude", str(self.root), "assist")
        subprocess.run(["python3", str(LAUNCHER.parent / "run_settings.py"), "save", str(run),
                        f"--repo={self.root}", "--cpus=6", "--mem=24G", f"--bind={self.data}:/data:rw",
                        "--overlap-job=77"], cwd=self.root, env=self.env, check=True, capture_output=True)
        self.agentrun("template", "save", "from-run", "--from", run.name)
        saved = json.loads((self.store / "from-run.json").read_text())
        self.assertEqual((saved["mode"], saved["agent"]), ("assist", "claude"))
        self.assertIn(f"{self.data}:/data:rw", saved["args"])
        self.assertNotIn("77", saved["args"])
        agent, _repo, cpus, mem, _name, *binds = self.expand("--template", "from-run")
        self.assertEqual((agent, cpus, mem, binds), ("claude", "6", "24G", [f"{self.data}:/data:rw"]))

    def test_invalid_names_and_tampered_files_are_rejected(self):
        self.agentrun("template", "save", "../escape", "--repo", ".", expected=2)
        self.store.mkdir(parents=True)
        (self.store / "bad.json").write_text(json.dumps({
            "version": 1, "mode": "assist", "agent": "codex", "submit": 0,
            "args": ["--repo", ".", "--overlap", "1"], "env": {}}))
        self.agentrun("template", "show", "bad", expected=2)
        self.assertNotIn("bad", self.agentrun("template", "list").stdout)


if __name__ == "__main__":
    unittest.main()
