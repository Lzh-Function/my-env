#!/usr/bin/env python3
"""GitHub CLI broker: runs allowlisted `gh` commands on behalf of the agent.

The broker runs in its own apptainer container, started next to the agent's
capsule. It is the only process that holds GH_TOKEN (passed with --env-file);
the agent's container never sees the token file or this process (separate PID
namespace). The agent talks to it through a Unix socket with `gh-client`,
which is bound over `gh` inside the capsule.

Request  (one JSON object, then EOF): {"argv": [...], "stdin": b64, "repo": "owner/name" | null}
Response (one JSON object):           {"stdout": b64, "stderr": b64, "code": int}

Guards:
- argv must match an entry in allowlist.txt: the subcommand words, then only
  the positional kinds and long flags that entry lists. Short flags, unlisted
  flags, URLs and extra positionals are rejected.
- Flag values are validated: --body-file must be "-" (the client sends file
  contents itself, so gh never opens a path here, e.g. /proc/self/environ),
  --repo and repository positionals must be OWNER/NAME, --head/--base branch
  names, --state/--limit/--json well formed.
- GH_BROKER_REPOS (comma-separated OWNER/NAME, from gh.env) pins the repositories
  commands may target; with exactly one, it is also the default.
- gh runs with a fixed environment and an empty working directory (no agent
  controlled git config is ever read), with prompts/browser/editor disabled.
- The token is redacted from anything sent back or logged; --comment values
  are not logged.
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWLIST_FILE = Path(os.environ.get("GH_BROKER_ALLOWLIST", HERE / "allowlist.txt"))
GH_BIN = os.environ.get("GH_BROKER_GH_BIN", "gh")
TIMEOUT_SECONDS = 300
MAX_REQUEST_BYTES = 16 * 1024 * 1024

REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NUMBER_RE = re.compile(r"^#?[0-9]+$")
# git branch names, without leading "-" and without ":" (so no URLs or OWNER:BRANCH)
BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/+@-]+$")
BOOLEAN_FLAGS = {"--draft"}
# Logged as <n chars> instead of the value.
UNLOGGED_FLAGS = {"--comment", "--title"}


def log(message: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{ts} {redact(message)}", file=sys.stderr, flush=True)


def redact(text: str) -> str:
    token = os.environ.get("GH_TOKEN", "")
    return text.replace(token, "***") if token else text


def pinned_repos() -> list[str]:
    return [r.strip() for r in os.environ.get("GH_BROKER_REPOS", "").split(",") if r.strip()]


def check_repo(value: str) -> str | None:
    if not REPO_RE.match(value):
        return f"repository must be OWNER/NAME: {value}"
    pinned = pinned_repos()
    if pinned and value.lower() not in (r.lower() for r in pinned):
        return f"repository {value} is not allowed (GH_BROKER_REPOS: {', '.join(pinned)})"
    return None


def check_flag_value(flag: str, value: str) -> str | None:
    if flag == "--body-file":
        return None if value == "-" else "--body-file must be '-' (the gh client sends file contents over stdin)"
    if flag == "--repo":
        return check_repo(value)
    if flag in ("--head", "--base"):
        return None if BRANCH_RE.match(value) else f"{flag} must be a branch name: {value}"
    if flag == "--state":
        return None if value in ("open", "closed", "merged", "all") else f"--state must be open, closed, merged or all: {value}"
    if flag == "--limit":
        return None if value.isdigit() else f"--limit must be a number: {value}"
    if flag == "--json":
        return None if re.match(r"^[A-Za-z]+(,[A-Za-z]+)*$", value) else f"--json must be comma-separated field names: {value}"
    return None


@dataclass
class Rule:
    words: list[str]
    positional: str | None = None  # "number", "number|branch", "repo"
    positional_required: bool = False
    flags: set[str] = field(default_factory=set)

    def describe(self) -> str:
        return " ".join(self.words)


def load_allowlist() -> list[Rule]:
    rules = []
    for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        head, _, flags = line.partition(":") if not line.startswith("-") else (line, "", "")
        rule = Rule(words=[], flags=set(flags.split()))
        for token in head.split():
            if token[0] in "<[":
                rule.positional = token[1:-1]
                rule.positional_required = token[0] == "<"
            else:
                rule.words.append(token)
        rules.append(rule)
    return rules


def check_positional(rule: Rule, value: str) -> str | None:
    kinds = (rule.positional or "").split("|")
    if "number" in kinds and NUMBER_RE.match(value):
        return None
    if "branch" in kinds and BRANCH_RE.match(value) and not value.isdigit():
        return None
    if "repo" in kinds:
        return check_repo(value)
    return f"`gh {rule.describe()}` does not accept {value!r} (expected {rule.positional or 'no positional argument'})"


def check_argv(argv: list[str], rules: list[Rule]) -> str | None:
    """Return a rejection reason, or None when the command may run."""
    if not argv:
        return "no gh subcommand given"
    rule = max((r for r in rules if argv[: len(r.words)] == r.words),
               key=lambda r: len(r.words), default=None)
    if rule is None:
        allowed = ", ".join(r.describe() for r in rules)
        return f"`gh {shlex.join(argv[:2])}` is not allowed through the broker. Allowed: {allowed}"
    args = argv[len(rule.words):]
    positionals = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            flag, eq, value = arg.partition("=")
            if flag not in rule.flags:
                allowed = " ".join(sorted(rule.flags)) or "none"
                return f"{flag} is not allowed with `gh {rule.describe()}` (allowed flags: {allowed})"
            if flag in BOOLEAN_FLAGS:
                if eq:
                    return f"{flag} does not take a value"
            else:
                if not eq:
                    if i + 1 >= len(args):
                        return f"{flag} needs a value"
                    i += 1
                    value = args[i]
                reason = check_flag_value(flag, value)
                if reason:
                    return reason
        elif arg.startswith("-") and arg != "-":
            return f"short flags are not accepted through the broker; use the long form ({arg})"
        else:
            positionals.append(arg)
        i += 1
    if len(positionals) > 1:
        return f"`gh {rule.describe()}` takes at most one positional argument"
    if positionals:
        if rule.positional is None:
            return f"`gh {rule.describe()}` does not take a positional argument"
        return check_positional(rule, positionals[0])
    if rule.positional_required:
        return f"`gh {rule.describe()}` needs {rule.positional}"
    return None


def loggable(argv: list[str]) -> str:
    out = []
    hide_next = False
    for arg in argv:
        if hide_next:
            out.append(f"<{len(arg)} chars>")
            hide_next = False
            continue
        flag, eq, value = arg.partition("=")
        if flag in UNLOGGED_FLAGS:
            if eq:
                out.append(f"{flag}=<{len(value)} chars>")
            else:
                out.append(arg)
                hide_next = True
            continue
        out.append(arg)
    return shlex.join(out)


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
            repo = str(repo) if repo else None
        except (ValueError, KeyError, TypeError) as exc:
            self.reply(b"", f"gh broker: bad request: {exc}\n".encode(), 2)
            return

        reason = check_argv(argv, load_allowlist())
        pinned = pinned_repos()
        # `repo` is what the client inferred (--repo, GH_REPO or the origin remote).
        # With a single pinned repository it is the default target; otherwise an
        # inferred repository must itself be allowed.
        if not reason and repo and check_repo(repo):
            if len(pinned) == 1:
                log(f"inferred repository {repo} is not allowed; using {pinned[0]}")
                repo = pinned[0]
            else:
                reason = check_repo(repo)
        if not reason and not repo and len(pinned) == 1:
            repo = pinned[0]
        if reason:
            log(f"denied gh {loggable(argv)}: {reason}")
            self.reply(b"", f"gh broker: {reason}\n".encode(), 1)
            return
        out, err, code = run_gh(argv, stdin, repo)
        log(f"ran gh {loggable(argv)} (repo={repo}) -> {code}")
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
