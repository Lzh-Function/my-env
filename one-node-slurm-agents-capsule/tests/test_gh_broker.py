"""gh の許可リスト・token 非公開・生成コマンドを検証する。外部通信はしない。"""

import base64
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "FAKE_GH_TOKEN_FOR_LOCAL_TEST_ONLY"
MOCK_GH = r'''#!/usr/bin/env python3
import json
import os
import sys
print(json.dumps({"argv":sys.argv[1:], "body":sys.stdin.read(), "cwd":os.getcwd(),
                  "env":dict(os.environ)}, ensure_ascii=False))
print(os.environ["GH_TOKEN"], file=sys.stderr)
'''


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gh-broker-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mock = self.root / "gh"
        mock.write_text(MOCK_GH)
        mock.chmod(0o755)
        self.socket = self.root / "gh.sock"
        self.log = (self.root / "broker.log").open("w+")
        self.addCleanup(self.log.close)
        env = dict(os.environ, GH_TOKEN=TOKEN, GH_BROKER_REPOS="owner/repo",
                   GH_BROKER_GH_BIN=str(mock), GITHUB_TOKEN="HOST_ALIAS_TOKEN",
                   GH_DEBUG="api", GIT_CONFIG_GLOBAL="/agent-controlled/gitconfig")
        self.proc = subprocess.Popen(["python3", str(ROOT / "runtime/gh-broker/gh_broker.py"), str(self.socket)],
                                     env=env, stdout=subprocess.DEVNULL, stderr=self.log)
        self.addCleanup(self.stop)
        deadline = time.monotonic() + 5
        while not self.socket.exists():
            self.assertIsNone(self.proc.poll())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.01)

    def stop(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)

    def request(self, argv, repo="owner/repo", body=b""):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(self.socket))
            sock.sendall(json.dumps({"argv":argv, "repo":repo, "stdin":base64.b64encode(body).decode()}).encode())
            sock.shutdown(socket.SHUT_WR)
            data = bytearray()
            while chunk := sock.recv(65536): data.extend(chunk)
        response = json.loads(data)
        return response["code"], base64.b64decode(response["stdout"]), base64.b64decode(response["stderr"])

    def test_allowed_command_fixed_env_and_token_redaction(self):
        code, out, err = self.request(["issue", "view", "12", "--json", "comments", "--repo", "owner/repo"])
        self.assertEqual(code, 0, err)
        self.assertNotIn(TOKEN.encode(), out + err)
        record = json.loads(out)
        self.assertEqual(record["env"]["GH_TOKEN"], "***")
        self.assertNotIn("GITHUB_TOKEN", record["env"])
        self.assertNotIn("GH_DEBUG", record["env"])
        self.assertEqual(record["env"]["GIT_CONFIG_GLOBAL"], "/dev/null")
        self.assertEqual(record["cwd"], record["env"]["HOME"])
        self.assertEqual(record["env"]["GH_PROMPT_DISABLED"], "1")

    def test_term_ignoring_gh_command_is_killed(self):
        binary = self.root / 'hung-gh'
        binary.write_text('#!/bin/sh\ntrap "" TERM\nwhile :; do sleep 1; done\n')
        binary.chmod(0o755)
        function = runpy.run_path(str(ROOT / 'runtime/gh-broker/gh_broker.py'))['run_gh']
        with mock.patch.dict(function.__globals__, GH_BIN=str(binary), TIMEOUT_SECONDS=0.2), \
                mock.patch.dict(os.environ, GH_TOKEN=TOKEN):
            start = time.monotonic()
            out, err, code = function(['issue', 'list'], b'', 'owner/repo')
        self.assertIn(code, (124, 137))
        self.assertIn(b'command timed out', err)
        self.assertLess(time.monotonic() - start, 4)
        self.assertNotIn(TOKEN.encode(), out + err)

    def test_backend_signal_exit_codes_are_valid_for_cli_clients(self):
        function = runpy.run_path(str(ROOT / 'runtime/gh-broker/gh_broker.py'))['run_gh']
        for result, expected in ((-9, 137), (-15, 143)):
            with self.subTest(signal=result), mock.patch.object(subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], result)):
                out, err, code = function(['issue', 'list'], b'', 'owner/repo')
                self.assertEqual(code, expected)
                self.assertEqual(b'command timed out' in err, expected == 137)

    def test_sensitive_subcommands_flags_and_paths_are_rejected(self):
        attempts = [
            ["auth", "token"], ["auth", "status", "--show-token"], ["api", "repos/owner/repo"],
            ["extension", "exec", "anything"], ["alias", "set", "evil", "auth token"],
            ["issue", "create", "--body-file", "/proc/self/environ"],
            ["issue", "create", "--template", "/tmp/file"],
            ["issue", "view", "https://github.com/owner/repo/issues/1"],
            ["pr", "create", "--head", "https://github.com/other/repo"],
            ["issue", "view", "1", "-R", "owner/repo"],
            ["issue", "view", "1", "--repo", "other/repo"],
            ["repo", "view", "other/repo"],
        ]
        for argv in attempts:
            with self.subTest(argv=argv):
                code, out, err = self.request(argv)
                self.assertEqual(code, 1)
                self.assertFalse(out)
                self.assertIn(b"gh broker:", err)

    def test_client_sends_body_contents_not_host_path(self):
        body = self.root / "body with spaces.md"
        body.write_text("body\nsecond line\n")
        result = subprocess.run([str(ROOT / "runtime/gh-broker/gh-client"), "issue", "comment", "1",
                                 "--body-file", str(body), "--repo", "owner/repo"], cwd=self.root,
                                env=dict(os.environ, AGENTRUN_GH_BROKER_SOCKET=str(self.socket)),
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["body"], body.read_text())
        self.assertIn("-", record["argv"])
        self.assertNotIn(str(body), record["argv"])

    def test_repo_pin_and_stdin_body(self):
        code, out, err = self.request(["issue", "create", "--title", "title", "--body-file", "-"],
                                      repo="fork/other", body=b"body from stdin")
        self.assertEqual(code, 0, err)
        record = json.loads(out)
        self.assertEqual(record["env"]["GH_REPO"], "owner/repo")
        self.assertEqual(record["body"], "body from stdin")

    def test_denial_and_title_logs_do_not_disclose_token(self):
        self.request(["issue", "create", "--title", TOKEN, "--body-file", "-"])
        self.request(["auth", "token", TOKEN])
        self.log.flush()
        text = (self.root / "broker.log").read_text()
        self.assertNotIn(TOKEN, text)
        self.assertIn("chars", text)



if __name__ == "__main__":
    unittest.main()
