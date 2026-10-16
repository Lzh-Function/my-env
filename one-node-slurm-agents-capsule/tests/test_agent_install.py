"""起動時更新を fake installer で検証する。外部の CLI はダウンロードしない。"""

import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "runtime/agentrun/install-agent.sh"

MOCK_INSTALLER = r'''#!/bin/sh
set -eu
export TEST_INSTALLED_CLI=__CLI__
python3 - "$@" <<'PY'
import json, os, sys
from pathlib import Path

cli = os.environ["TEST_INSTALLED_CLI"]
home = Path(os.environ["HOME"])
bin_dir = home / ".local/bin"
args = sys.argv[1:]
assert home != Path(os.environ["TEST_AUTH_HOME"])
assert not (home / "auth-marker").exists()
if cli == "claude":
    assert args == ["latest"]
elif cli == "codex":
    assert os.environ["CODEX_RELEASE"] == "latest"
    assert os.environ["CODEX_NON_INTERACTIVE"] == "1"
    assert os.environ["CODEX_INSTALL_DIR"] == str(bin_dir)
    assert os.environ["CODEX_HOME"] == str(home / ".codex")
    assert os.environ["CODEX_INSTALL_DAEMON_ONLY"] == "0"
else:
    raise AssertionError("unsupported mock CLI: " + cli)
with Path(os.environ["TEST_INSTALL_CALLS"]).open("a") as stream:
    stream.write(json.dumps({"cli":cli, "home":str(home), "args":args}) + "\n")
if os.environ.get("TEST_FAILURE") == "install":
    print("intentional installer failure", file=sys.stderr)
    sys.exit(17)
if os.environ.get("TEST_FAILURE") == "missing":
    sys.exit(0)
version = cli + " " + os.environ["TEST_RELEASE"]
script = "#!/usr/bin/env python3\n" + r"""
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ["--version"]:
    if os.environ.get("TEST_FAILURE") == "version":
        sys.exit(19)
    print(VERSION)
else:
    Path(os.environ["TEST_CLI_CALL"]).write_text(json.dumps({"version":VERSION, "args":sys.argv[1:], "home":os.environ["HOME"]}))
    sys.exit(int(os.environ.get("TEST_CLI_RC", "0")))
""".replace("VERSION", repr(version))
bin_dir.mkdir(parents=True, exist_ok=True)
binary = bin_dir / cli
binary.write_text(script)
binary.chmod(0o755)
print("mock installer completed")
PY
'''

MOCK_CURL = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
if os.environ.get("TEST_FAILURE") == "fetch":
    print("intentional download failure", file=sys.stderr)
    sys.exit(22)
args = sys.argv[1:]
url = next(arg for arg in args if arg.startswith("https://"))
assert "claude.ai" in url or "chatgpt.com" in url
cli = "claude" if "claude.ai" in url else "codex"
template = Path(os.environ["TEST_INSTALL_TEMPLATE"]).read_text()
Path(args[args.index("-o")+1]).write_text(template.replace("__CLI__", cli))
'''

MOCK_TIMEOUT = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == "--foreground"
with Path(os.environ["TEST_TIMEOUT_CALLS"]).open("a") as stream:
    stream.write(json.dumps(args[:2]) + "\n")
if args[1] == "600" and os.environ.get("TEST_FAILURE") == "timeout":
    sys.exit(124)
os.execvp(args[2], args[2:])
'''


class AgentInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent install with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.cache = self.run / "cache"
        self.home = self.root / "auth-home"
        self.home.mkdir()
        (self.home / "auth-marker").write_text("keep auth and history")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, text in (("curl", MOCK_CURL), ("timeout", MOCK_TIMEOUT)):
            path = self.bin / name
            path.write_text(text)
            path.chmod(0o755)
        template = self.root / "installer-template"
        template.write_text(MOCK_INSTALLER)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(self.home),
                        TEST_AUTH_HOME=str(self.home), TEST_INSTALL_TEMPLATE=str(template), TEST_RELEASE="1.0.0",
                        TEST_INSTALL_CALLS=str(self.root / "installs.jsonl"), TEST_CLI_CALL=str(self.root / "cli.json"),
                        TEST_TIMEOUT_CALLS=str(self.root / "timeouts.jsonl"),
                        TEST_RUN_DIR=str(self.run), TEST_CACHE_DIR=str(self.cache), TEST_WORKSPACE=str(self.root))

    def install(self, agent="codex", expected=0):
        result = subprocess.run(["bash", str(INSTALLER), agent, str(self.run), str(self.cache)],
                                env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual((self.home / "auth-marker").read_text(), "keep auth and history")
        return result

    def test_each_agent_installs_latest_in_its_own_home_and_records_version(self):
        for agent, cli in (("claude", "claude"), ("codex", "codex")):
            with self.subTest(agent=agent):
                result = self.install(agent)
                bin_dir = Path(result.stdout.strip())
                self.assertTrue((bin_dir / cli).is_file())
                self.assertTrue(bin_dir.is_relative_to(self.cache))
                metadata = json.loads((self.run / "artifacts/agent-cli.json").read_text())
                self.assertEqual(metadata["version"], f"{cli} 1.0.0")
                self.assertEqual(metadata["requested_release"], "latest")
                self.assertEqual(metadata["path"], str(bin_dir / cli))
                self.assertEqual(len(metadata["installer_sha256"]), 64)
                self.assertIn("mock installer completed", (self.run / "live/agent_install.log").read_text())
        timeouts = [json.loads(line)[1] for line in (self.root / "timeouts.jsonl").read_text().splitlines()]
        self.assertEqual(timeouts, ["600", "30"] * 2)

    def test_next_start_resolves_latest_again_without_reusing_old_binary(self):
        first = self.install("codex").stdout.strip()
        self.env["TEST_RELEASE"] = "2.0.0"
        second = self.install("codex").stdout.strip()
        self.assertNotEqual(first, second)
        metadata = json.loads((self.run / "artifacts/agent-cli.json").read_text())
        self.assertEqual(metadata["version"], "codex 2.0.0")
        calls = [json.loads(line) for line in (self.root / "installs.jsonl").read_text().splitlines()]
        self.assertNotEqual(calls[0]["home"], calls[1]["home"])

    def launcher_command(self):
        script = '''source "$1"
EXTRA_BINDS=()
write_plan experiment codex "$PWD" '' 0 00:10:00 task "$TEST_RUN_DIR" agent batch
'''
        result = subprocess.run(["bash", "-c", script, "bash", str(ROOT / "runtime/agentrun/agentrun")],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = (self.run / "apptainer_exec.sh").read_text().splitlines()[-1]
        args = shlex.split(launch)
        self.assertIn(f"{INSTALLER}:/opt/agentrun/install-agent.sh:ro", args)
        cmd = args[-1].replace("/workspace", '"$TEST_WORKSPACE"').replace("/runs/prompt.txt", '"$TEST_RUN_DIR/prompt.txt"')
        return cmd.replace("bash /opt/agentrun/install-agent.sh codex",
                           f'bash {shlex.quote(str(INSTALLER))} codex "$TEST_RUN_DIR" "$TEST_CACHE_DIR"')

    def test_launcher_uses_new_cli_and_original_auth_home_and_preserves_exit(self):
        old = self.bin / "codex"
        old.write_text("#!/bin/sh\nexit 99\n")
        old.chmod(0o755)
        self.env["TEST_CLI_RC"] = "42"
        result = subprocess.run(["bash", "-c", self.launcher_command()], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        launched = json.loads((self.root / "cli.json").read_text())
        self.assertEqual(launched["version"], "codex 1.0.0")
        self.assertEqual(launched["home"], str(self.home))
        self.assertEqual(launched["args"][0], "exec")

    def test_download_install_version_missing_and_timeout_fail_before_agent_start(self):
        cmd = self.launcher_command()
        for failure, code in (("fetch", 22), ("install", 17), ("version", 19), ("missing", 1), ("timeout", 124)):
            with self.subTest(failure=failure):
                self.env["TEST_FAILURE"] = failure
                result = subprocess.run(["bash", "-c", cmd], cwd=self.root, env=self.env,
                                        capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn("installation failed", result.stderr)
                self.assertFalse((self.root / "cli.json").exists())
                self.assertFalse((self.run / "artifacts/agent-cli.json").exists())


if __name__ == "__main__":
    unittest.main()
