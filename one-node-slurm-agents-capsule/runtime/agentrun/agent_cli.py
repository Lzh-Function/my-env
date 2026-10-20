"""Provider-specific, isolated reviewer execution. Never falls back to the worker."""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from review_snapshot import atomic_json

IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
BASE_ENV = {
    "PATH",
    "LANG",
    "LC_ALL",
    "TERM",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "NODE_EXTRA_CA_CERTS",
}


class ProviderError(ValueError):
    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


def failure_kind(text):
    text = text.lower()
    if any(p in text for p in ("rate limit", "rate_limit", "usage limit", "quota")):
        return "rate_limit"
    if any(
        p in text
        for p in ("unauthorized", "authentication", "invalid api key", "login required")
    ):
        return "authentication"
    if any(p in text for p in ("refusal", "refused")):
        return "refusal"
    return "provider_failed"


def stop(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    # Also terminate surviving descendants when the leader has already exited.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def process_identity(pid):
    path = Path("/proc") / str(pid)
    if path.stat().st_uid != os.getuid():
        raise ValueError("Reviewer process owner changed")
    fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
    return {
        "pid": pid,
        "start_ticks": fields[19],
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


def cleanup_recorded_processes(root):
    """Recover our live process groups after a service crash without trusting PID alone."""
    paths = list(Path(root).glob("review-*/turns/*/status.json"))
    paths += list(Path(root).glob("runtime/*/*/status.json"))
    groups = []
    for path in paths:
        data = json.loads(path.read_text())
        if data.get("status") != "running" or not isinstance(data.get("pid"), int):
            continue
        try:
            if process_identity(data["pid"]) != {
                k: data[k] for k in ("pid", "start_ticks", "boot_id")
            }:
                continue
            os.killpg(data["pid"], signal.SIGTERM)
            groups.append(data["pid"])
        except (ProcessLookupError, FileNotFoundError):
            continue
    deadline = time.monotonic() + 2
    while groups and time.monotonic() < deadline:
        remaining = []
        for pid in groups:
            try:
                os.killpg(pid, 0)
                remaining.append(pid)
            except ProcessLookupError:
                pass
        groups = remaining
        if groups:
            time.sleep(0.05)
    for pid in groups:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def environment(home, runtime, provider):
    env = {k: v for k, v in os.environ.items() if k in BASE_ENV}
    for key in tuple(env):
        if (
            provider == "codex"
            and (key.startswith("ANTHROPIC_") or key == "CLAUDE_CODE_OAUTH_TOKEN")
        ) or (
            provider == "claude"
            and (key.startswith("OPENAI_") or key == "CODEX_API_KEY")
        ):
            del env[key]
    env.update(
        HOME=str(home),
        CODEX_HOME=str(home / ".codex"),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_DATA_HOME=str(home / ".local/share"),
        AGENTRUN_ROLE="reviewer",
        AGENTRUN_DIR=str(runtime),
        CLAUDE_CODE_TMPDIR=str(runtime / "scratch"),
        CLAUDE_CODE_DISABLE_AUTO_MEMORY="1",
        DISABLE_AUTOUPDATER="1",
        ENABLE_CLAUDEAI_MCP_SERVERS="false",
        PYTHONNOUSERSITE="1",
    )
    return env


def prepare_home(home, persisted, provider, worker_home):
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    persisted.mkdir(parents=True, exist_ok=True, mode=0o700)
    mounts = {
        "codex": (".codex/sessions", ".codex/archived_sessions", ".codex/sqlite"),
        "claude": (
            ".claude/projects",
            ".claude/file-history",
            ".claude/todos",
            ".claude/tasks",
            ".claude/plans",
        ),
    }
    for relative in mounts[provider]:
        link = home / relative
        target = persisted / relative
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.exists():
            link.symlink_to(target, target_is_directory=True)
    relative = (
        ".codex/auth.json" if provider == "codex" else ".claude/.credentials.json"
    )
    source, target = worker_home / relative, home / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite refreshed credentials in the dedicated reviewer HOME.
    if source.is_file() and not target.exists():
        shutil.copyfile(source, target)
        target.chmod(0o600)
    if provider == "claude":
        atomic_json(home / ".claude.json", {"hasCompletedOnboarding": True})
    return target.is_file() or bool(
        os.environ.get("OPENAI_API_KEY" if provider == "codex" else "ANTHROPIC_API_KEY")
        or (provider == "codex" and os.environ.get("CODEX_API_KEY"))
        or (
            provider == "claude"
            and (
                os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
            )
        )
    )


class Reviewer:
    def __init__(
        self,
        provider,
        home,
        persisted,
        runtime,
        worker_home,
        installer,
        cache,
        binary=None,
        model=None,
        effort=None,
    ):
        self.provider, self.home, self.runtime = provider, Path(home), Path(runtime)
        self.runtime.mkdir(parents=True, exist_ok=True)
        if not prepare_home(self.home, Path(persisted), provider, Path(worker_home)):
            raise ProviderError(
                "missing_authentication",
                "Reviewer authentication is unavailable: " + provider,
            )
        self.env = environment(self.home, self.runtime, provider)
        self.binary, self.installer, self.cache = binary, installer, cache
        self.model, self.effort = model, effort
        self.process = None
        self.temporary = None
        self.checked = False
        self.last_metadata = {}
        self.last_session_id = None
        self.last_exit_code = None
        atomic_json(
            self.home / ".claude/settings.json",
            {"disableAllHooks": True, "autoMemoryEnabled": False},
        )
        atomic_json(self.runtime / "empty-mcp.json", {"mcpServers": {}})
        if provider == "codex":
            (self.home / ".codex/config.toml").write_text(
                'sandbox_mode = "read-only"\napproval_policy = "never"\n'
                + "sqlite_home = "
                + json.dumps(str(self.home / ".codex/sqlite"))
                + "\n"
            )
            temporary = self.home / ".codex/tmp"
            if not temporary.exists():
                import tempfile

                self.temporary = Path(
                    tempfile.mkdtemp(prefix="review-codex-", dir="/tmp")
                )
                temporary.symlink_to(self.temporary)

    def close(self):
        stop(self.process)
        if self.temporary:
            shutil.rmtree(self.temporary, ignore_errors=True)
            (self.home / ".codex/tmp").unlink(missing_ok=True)

    def execute(self, command, directory, turn, prompt, timeout, cancelled):
        turn.mkdir(parents=True, exist_ok=True)
        (turn / "prompt.txt").write_text(prompt)
        started = time.monotonic()
        scratch = self.runtime / "scratch" / turn.name
        scratch.mkdir(parents=True, exist_ok=True)
        child_env = dict(self.env, CLAUDE_CODE_TMPDIR=str(scratch))
        atomic_json(
            turn / "status.json", {"status": "prepared", "created_at": time.time()}
        )
        with (
            (turn / "stdout.jsonl").open("w") as stdout,
            (turn / "stderr.log").open("w") as stderr,
            (turn / "prompt.txt").open("rb") as stdin,
        ):
            gate = turn / "launch-ready"
            gate.unlink(missing_ok=True)
            guarded = [
                sys.executable,
                str(Path(__file__).resolve()),
                "_launch",
                str(os.getpid()),
                str(gate),
                *command,
            ]
            self.process = subprocess.Popen(
                guarded,
                cwd=directory,
                env=child_env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            try:
                identity = process_identity(self.process.pid)
                atomic_json(
                    turn / "status.json",
                    dict(identity, status="running", created_at=time.time()),
                )
                # No provider starts until its identity has been persisted.
                gate.touch()
                while self.process.poll() is None:
                    if cancelled.is_set():
                        raise InterruptedError("Review cancelled")
                    if time.monotonic() - started > timeout:
                        raise TimeoutError("Reviewer execution deadline exceeded")
                    if (
                        sum(p.stat().st_size for p in turn.glob("*") if p.is_file())
                        > 32 * 1024 * 1024
                    ):
                        raise ValueError("Reviewer output exceeds size limit")
                    time.sleep(0.05)
                code = self.process.returncode
                if code:
                    stdout.flush()
                    stderr.flush()
                    diagnostic = (turn / "stderr.log").read_text(errors="replace")[
                        -65536:
                    ]
                    raise ProviderError(
                        failure_kind(diagnostic),
                        f"Reviewer process failed (exit {code}); see {turn.name}/stderr.log",
                    )
            finally:
                stop(self.process)
                self.last_exit_code = self.process.returncode
                atomic_json(
                    turn / "status.json",
                    {
                        "status": "success"
                        if self.process.returncode == 0
                        else "failed",
                        "exit_code": self.process.returncode,
                        "elapsed_seconds": time.monotonic() - started,
                    },
                )
                self.process = None
        return time.monotonic() - started

    def ensure(self, cancelled):
        if not self.binary:
            location = self.runtime / "installation"
            metadata = location / "artifacts/agent-cli.json"
            if not metadata.exists():
                try:
                    self.execute(
                        [
                            "bash",
                            str(self.installer),
                            self.provider,
                            str(location),
                            str(self.cache),
                        ],
                        self.home,
                        self.runtime / "install",
                        "",
                        800,
                        cancelled,
                    )
                except ProviderError as error:
                    raise ProviderError("installation_failed", str(error)) from error
            info = json.loads(metadata.read_text())
            if info["agent"] != self.provider or not Path(
                info["path"]
            ).resolve().is_relative_to(Path(self.cache).resolve()):
                raise ProviderError(
                    "installation_failed", "Reviewer installation metadata is invalid"
                )
            self.binary = info["path"]
        if not self.checked:
            flags = (
                ("--json", "--output-schema", "--ignore-user-config", "--ignore-rules")
                if self.provider == "codex"
                else (
                    "--restricted",
                    "--safe-mode",
                    "--tools",
                    "--strict-mcp-config",
                    "--permission-prompts",
                    "--json-schema",
                )
            )
            probes = (
                (
                    [self.binary, "exec", "--help"],
                    [self.binary, "exec", "resume", "--help"],
                )
                if self.provider == "codex"
                else ([self.binary, "--help"],)
            )
            for number, arguments in enumerate(probes):
                probe = self.runtime / f"probe-help-{number}"
                self.execute(arguments, self.home, probe, "", 15, cancelled)
                help_text = (probe / "stdout.jsonl").read_text()
                if any(flag not in help_text for flag in flags):
                    raise ProviderError(
                        "unsupported_cli",
                        "Installed reviewer lacks required restriction/continuation flags",
                    )
            probe = self.runtime / "probe-version"
            self.execute(
                [self.binary, "--version"], self.home, probe, "", 15, cancelled
            )
            version = (probe / "stdout.jsonl").read_text().strip()
            atomic_json(
                self.runtime / "cli.json",
                {
                    "provider": self.provider,
                    "path": self.binary,
                    "version": version,
                    "model_requested": self.model,
                },
            )
            self.checked = True

    def turn(self, directory, prompt, schema, turn, session_id, timeout, cancelled):
        self.last_session_id = session_id
        self.last_exit_code = None
        self.ensure(cancelled)
        schema_path = turn / "schema.json"
        turn.mkdir(parents=True, exist_ok=True)
        atomic_json(schema_path, schema)
        if session_id and not IDENT.fullmatch(session_id):
            raise ValueError("Invalid native session ID")
        if self.provider == "codex":
            command = [self.binary, "exec"]
            if session_id:
                command += ["resume", session_id]
            command += [
                "--json",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "-c",
                'sandbox_mode="read-only"',
                "-c",
                'approval_policy="never"',
                "-c",
                "sqlite_home=" + json.dumps(str(self.home / ".codex/sqlite")),
                "-c",
                "project_doc_max_bytes=0",
                "--output-schema",
                str(schema_path),
                "-o",
                str(turn / "answer.json"),
            ]
            if self.model:
                command += ["--model", self.model]
            if self.effort:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.effort)]
            command += ["-"]
        else:
            command = [
                self.binary,
                "--print",
                "--restricted",
                "--safe-mode",
                "--disable-slash-commands",
                "--tools",
                "Read,Glob,Grep",
                "--allowedTools",
                "Read,Glob,Grep",
                "--permission-mode",
                "dontAsk",
                "--permission-prompts",
                "none",
                "--setting-sources",
                "",
                "--settings",
                str(self.home / ".claude/settings.json"),
                "--strict-mcp-config",
                "--mcp-config",
                str(self.runtime / "empty-mcp.json"),
                "--output-format",
                "json",
                "--json-schema",
                json.dumps(schema),
            ]
            if session_id:
                command += ["--resume", session_id]
            if self.model:
                command += ["--model", self.model]
            if self.effort:
                command += ["--effort", self.effort]
        elapsed = self.execute(command, directory, turn, prompt, timeout, cancelled)
        raw = (turn / "stdout.jsonl").read_text()
        if self.provider == "codex":
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
            sessions = [
                r.get("thread_id") for r in records if r.get("type") == "thread.started"
            ]
            if (
                sessions
                and isinstance(sessions[-1], str)
                and IDENT.fullmatch(sessions[-1])
            ):
                self.last_session_id = sessions[-1]
            if not any(r.get("type") == "turn.completed" for r in records):
                raise ProviderError(
                    failure_kind(raw[-65536:]), "Codex did not complete its turn"
                )
            ident = sessions[-1] if sessions else session_id
            result = json.loads((turn / "answer.json").read_text())
            metadata = {
                "model": next(
                    (
                        r["model"]
                        for r in reversed(records)
                        if isinstance(r.get("model"), str)
                    ),
                    None,
                ),
                "usage": next(
                    (
                        r["usage"]
                        for r in reversed(records)
                        if isinstance(r.get("usage"), dict)
                    ),
                    None,
                ),
            }
        else:
            envelope = json.loads(raw)
            if isinstance(envelope.get("session_id"), str) and IDENT.fullmatch(
                envelope["session_id"]
            ):
                self.last_session_id = envelope["session_id"]
            if envelope.get("is_error") or envelope.get("subtype") != "success":
                raise ProviderError(
                    failure_kind(raw[-65536:]),
                    "Claude returned an unsuccessful final response",
                )
            ident = envelope.get("session_id")
            result = envelope.get("structured_output")
            metadata = {
                "model": envelope.get("model"),
                "usage": envelope.get("usage"),
                "model_usage": envelope.get("modelUsage"),
                "estimated_cost_usd": envelope.get("total_cost_usd"),
            }
        if (
            not isinstance(ident, str)
            or not IDENT.fullmatch(ident)
            or (session_id and ident != session_id)
        ):
            raise ValueError("Missing or mismatched reviewer session ID")
        self.last_metadata = dict(
            json.loads((self.runtime / "cli.json").read_text()), **metadata
        )
        return result, ident, elapsed


if __name__ == "__main__":
    if len(sys.argv) < 5 or sys.argv[1] != "_launch":
        sys.exit(2)
    parent, gate = int(sys.argv[2]), Path(sys.argv[3])
    deadline = time.monotonic() + 10
    while not gate.exists():
        if os.getppid() != parent or time.monotonic() >= deadline:
            sys.exit(125)
        time.sleep(0.01)
    if os.getppid() != parent:
        sys.exit(125)
    os.execvpe(sys.argv[4], sys.argv[4:], os.environ)
