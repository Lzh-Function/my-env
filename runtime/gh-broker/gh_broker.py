#!/usr/bin/env python3
"""GitHub CLI broker: runs allowlisted `gh` commands on behalf of the agent.

The broker runs in its own apptainer container, started next to the agent's
capsule. It is the only process that holds GH_TOKEN (passed with --env-file);
the agent's container never sees the token file or this process (separate PID
namespace). The agent talks to it through a Unix socket with `gh-client`,
which is bound over `gh` inside the capsule.

Request  (one JSON object, then EOF): {"argv": [...], "stdin": b64, "repo": "owner/name" | null}
Response (one JSON object):           {"stdout": b64, "stderr": b64, "code": int}

Guards, in order:
- argv must start with a subcommand listed in allowlist.txt ("issue list", ...),
  with no flags before the subcommand words.
- --body-file / -F may only read stdin ("-"): the client sends file contents
  itself, so a path can never make gh read files (e.g. /proc/self/environ)
  in here. --recover and --hostname are rejected.
- gh runs with a fixed environment, an empty working directory (no agent
  controlled git config is ever read), prompts/browser/editor disabled, and
  GH_REPO validated as OWNER/REPO.
- The token is redacted from anything sent back or logged.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shlex
import socketserver
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWLIST_FILE = Path(os.environ.get("GH_BROKER_ALLOWLIST", HERE / "allowlist.txt"))
GH_BIN = os.environ.get("GH_BROKER_GH_BIN", "gh")
TIMEOUT_SECONDS = 300
MAX_REQUEST_BYTES = 16 * 1024 * 1024

REPO_RE = re.compile(r"^(github\.com/)?[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
BODY_FILE_FLAGS = ("--body-file", "-F")
REJECTED_FLAGS = ("--recover", "--hostname")
REPO_FLAGS = ("--repo", "-R")


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{ts} {redact(message)}", file=sys.stderr, flush=True)


def redact(text: str) -> str:
    token = os.environ.get("GH_TOKEN", "")
    return text.replace(token, "***") if token else text


def load_allowlist() -> list[list[str]]:
    entries = []
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line.split())
    return entries


def check_argv(argv: list[str], allowlist: list[list[str]]) -> str | None:
    """Return a rejection reason, or None when the command may run."""
    if not argv:
        return "no gh subcommand given"
    matched = next((e for e in allowlist if argv[: len(e)] == e), None)
    if matched is None:
        allowed = ", ".join(" ".join(e) for e in allowlist)
        hint = " (write subcommands before any flags)" if argv[0].startswith("-") else ""
        return f"`gh {shlex.join(argv[:2])}` is not allowed through the broker{hint}. Allowed: {allowed}"
    args = argv[len(matched):]
    for i, arg in enumerate(args):
        name, eq, value = arg.partition("=")
        if name in REJECTED_FLAGS:
            return f"{name} is not allowed through the broker"
        if name in BODY_FILE_FLAGS:
            value = value if eq else (args[i + 1] if i + 1 < len(args) else "")
            if value != "-":
                return f"{name} must be '-' (the gh client sends file contents over stdin)"
        if name in REPO_FLAGS:
            value = value if eq else (args[i + 1] if i + 1 < len(args) else "")
            if not REPO_RE.match(value):
                return f"{name} must be OWNER/REPO"
    return None


def run_gh(argv: list[str], stdin: bytes, repo: str | None) -> tuple[bytes, bytes, int]:
    with tempfile.TemporaryDirectory(prefix="gh-broker-") as work:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": work,
            "GH_CONFIG_DIR": os.path.join(work, "gh"),
            "GH_TOKEN": os.environ.get("GH_TOKEN", ""),
            "GH_PROMPT_DISABLED": "1",
            "GH_NO_UPDATE_NOTIFIER": "1",
            "GH_BROWSER": "false",
            "BROWSER": "false",
            "GH_EDITOR": "false",
            "NO_COLOR": "1",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CEILING_DIRECTORIES": work,
            "LANG": "C.UTF-8",
        }
        if repo:
            env["GH_REPO"] = repo
        try:
            proc = subprocess.run(
                [GH_BIN, *argv], input=stdin, capture_output=True,
                cwd=work, env=env, timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return b"", b"gh broker: command timed out\n", 124
        except FileNotFoundError:
            return b"", b"gh broker: gh is not installed in the image (rebuild base-system.sif)\n", 127
        return proc.stdout, proc.stderr, proc.returncode


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.read(MAX_REQUEST_BYTES + 1)
        try:
            if len(raw) > MAX_REQUEST_BYTES:
                raise ValueError("request too large")
            request = json.loads(raw)
            argv = [str(a) for a in request["argv"]]
            stdin = base64.b64decode(request.get("stdin") or "")
            repo = request.get("repo")
            if repo is not None and not REPO_RE.match(str(repo)):
                repo = None
        except (ValueError, KeyError, TypeError) as exc:
            self.reply(b"", f"gh broker: bad request: {exc}\n".encode(), 2)
            return

        reason = check_argv(argv, load_allowlist())
        if reason:
            log(f"denied gh {shlex.join(argv)}: {reason}")
            self.reply(b"", f"gh broker: {reason}\n".encode(), 1)
            return
        out, err, code = run_gh(argv, stdin, repo)
        log(f"ran gh {shlex.join(argv)} (repo={repo}) -> {code}")
        self.reply(out, err, code)

    def reply(self, out: bytes, err: bytes, code: int) -> None:
        token = os.environ.get("GH_TOKEN", "").encode()
        if token:
            out, err = out.replace(token, b"***"), err.replace(token, b"***")
        body = {
            "stdout": base64.b64encode(out).decode(),
            "stderr": base64.b64encode(err).decode(),
            "code": code,
        }
        self.wfile.write(json.dumps(body).encode())


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: gh_broker.py SOCKET_PATH", file=sys.stderr)
        return 2
    if not os.environ.get("GH_TOKEN"):
        log("GH_TOKEN is not set; refusing to start")
        return 1
    socket_path = sys.argv[1]
    if os.path.exists(socket_path):
        os.unlink(socket_path)
    os.umask(0o077)
    load_allowlist()
    with Server(socket_path, Handler) as server:
        log(f"listening on {socket_path}")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
