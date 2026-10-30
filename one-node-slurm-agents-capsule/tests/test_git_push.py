"""Real Git pushes through the broker to a local Smart HTTP backend; no GitHub calls."""

import base64
import http.client
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/gh-broker"))
from git_bridge import GitServer, UnixConnection

TOKEN = "SYNTHETIC_GIT_PUSH_TOKEN"


class GitPushTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="git push broker ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "git-remote-agentrun").symlink_to(
            ROOT / "runtime/gh-broker/git-remote-agentrun"
        )
        self.socket = self.root / "git.sock"
        self.env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("GIT_", "GH_", "GITHUB_"))
        }
        self.env.update(
            HOME=str(self.home),
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            AGENTRUN_GIT_BROKER_SOCKET=str(self.socket),
        )
        (self.home / ".gitconfig").write_text(
            '[url "agentrun://github.com/"]\n pushInsteadOf = https://github.com/\n pushInsteadOf = git@github.com:\n pushInsteadOf = ssh://git@github.com/\n'
        )
        self.bare = self.root / "upstream/owner/repo.git"
        self.bare.parent.mkdir(parents=True)
        self.git("init", "--bare", str(self.bare))
        self.git("-C", str(self.bare), "config", "http.receivepack", "true")
        self.repo = self.root / "client"
        self.git("init", "-b", "main", str(self.repo))
        self.git("-C", str(self.repo), "config", "user.name", "Fixture")
        self.git(
            "-C", str(self.repo), "config", "user.email", "fixture@example.invalid"
        )
        (self.repo / "code.txt").write_text("committed evidence\n")
        self.git("-C", str(self.repo), "add", ".")
        self.git("-C", str(self.repo), "commit", "-m", "fixture")
        self.git(
            "-C",
            str(self.repo),
            "remote",
            "add",
            "origin",
            "https://github.com/owner/repo.git",
        )
        self.requests = []
        requests, project = self.requests, self.bare.parent.parent

        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                self.serve()

            def do_POST(self):
                self.serve()

            def serve(self):
                requests.append(
                    (
                        self.command,
                        self.path,
                        self.headers.get("Authorization"),
                        self.headers.get("Transfer-Encoding"),
                    )
                )
                if self.headers.get("Transfer-Encoding") == "chunked":
                    chunks = []
                    while True:
                        size = int(self.rfile.readline().strip(), 16)
                        if not size:
                            self.rfile.readline()
                            break
                        chunks.append(self.rfile.read(size))
                        self.rfile.read(2)
                    body = b"".join(chunks)
                else:
                    body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                parsed = urlsplit(self.path)
                env = dict(
                    self.server.test_env,
                    GIT_PROJECT_ROOT=str(project),
                    GIT_HTTP_EXPORT_ALL="1",
                    PATH_INFO=parsed.path,
                    QUERY_STRING=parsed.query,
                    REQUEST_METHOD=self.command,
                    CONTENT_TYPE=self.headers.get("Content-Type", ""),
                    CONTENT_LENGTH=str(len(body)),
                    REMOTE_USER="fixture",
                )
                result = subprocess.run(
                    ["git", "http-backend"],
                    input=body,
                    capture_output=True,
                    env=env,
                    check=True,
                )
                headers, _, data = result.stdout.partition(b"\r\n\r\n")
                status = 200
                fields = []
                for line in headers.decode().splitlines():
                    name, _, value = line.partition(":")
                    if name.lower() == "status":
                        status = int(value.strip().split()[0])
                    else:
                        fields.append((name, value.strip()))
                self.send_response(status)
                for name, value in fields:
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
        self.http.test_env = self.env
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()
        self.log = []
        self.broker = GitServer(
            str(self.socket),
            lambda repo: (
                None if repo.lower() == "owner/repo" else "repository is not allowed"
            ),
            lambda: TOKEN,
            self.log.append,
            upstream=lambda: http.client.HTTPConnection(
                "127.0.0.1", self.http.server_port, timeout=10
            ),
        )
        self.thread = threading.Thread(target=self.broker.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.broker.shutdown()
        self.broker.server_close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)
        self.http_thread.join(timeout=2)

    def git(self, *args, expected=0):
        result = subprocess.run(
            ["git", *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        return result

    def test_https_and_ssh_remotes_push_real_commits_without_client_credentials(self):
        for i, url in enumerate(
            (
                "https://github.com/owner/repo.git",
                "git@github.com:owner/repo.git",
                "ssh://git@github.com/owner/repo.git",
            )
        ):
            self.git("-C", str(self.repo), "remote", "set-url", "origin", url)
            self.git(
                "-C", str(self.repo), "push", "origin", f"HEAD:refs/heads/probe-{i}"
            )
            local = self.git("-C", str(self.repo), "rev-parse", "HEAD").stdout.strip()
            remote = self.git(
                "-C", str(self.bare), "rev-parse", f"refs/heads/probe-{i}"
            ).stdout.strip()
            self.assertEqual(local, remote)
            self.assertEqual(
                self.git(
                    "-C", str(self.repo), "remote", "get-url", "origin"
                ).stdout.strip(),
                url,
            )
        expected = (
            "Basic " + base64.b64encode(("x-access-token:" + TOKEN).encode()).decode()
        )
        self.assertTrue(self.requests)
        self.assertTrue(all(request[2] == expected for request in self.requests))
        self.assertNotIn(TOKEN, str(self.env) + str(self.log))

    def test_chunked_push_transfers_pack_without_buffering_it_in_the_protocol(self):
        (self.repo / "large.bin").write_bytes(os.urandom(200000))
        self.git("-C", str(self.repo), "add", ".")
        self.git("-C", str(self.repo), "commit", "-m", "binary")
        self.git(
            "-C",
            str(self.repo),
            "-c",
            "http.postBuffer=1024",
            "push",
            "origin",
            "HEAD:refs/heads/chunked",
        )
        self.assertTrue(any(request[3] == "chunked" for request in self.requests))
        result = subprocess.run(
            ["git", "--git-dir", str(self.bare), "show", "chunked:large.bin"],
            capture_output=True,
            check=True,
        )
        self.assertEqual(result.stdout, (self.repo / "large.bin").read_bytes())

    def test_wrong_repository_is_denied_without_redirecting_to_the_pinned_repo(self):
        self.git(
            "-C",
            str(self.repo),
            "remote",
            "set-url",
            "origin",
            "https://github.com/owner/other.git",
        )
        result = subprocess.run(
            ["git", "-C", str(self.repo), "push", "origin", "HEAD:refs/heads/main"],
            check=False,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.requests, [])

    def test_arbitrary_api_urls_and_non_push_services_never_reach_upstream(self):
        for path in (
            "/api/user",
            "/owner/repo.git/info/refs?service=git-upload-pack",
            "/owner/../info/refs?service=git-receive-pack",
            "https://other.example/owner/repo.git/info/refs?service=git-receive-pack",
        ):
            connection = UnixConnection(str(self.socket))
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                self.assertEqual(response.status, 400, path)
                response.read()
            finally:
                connection.close()
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
