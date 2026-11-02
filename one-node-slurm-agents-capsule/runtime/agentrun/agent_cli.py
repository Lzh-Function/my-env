"""Provider-specific, isolated reviewer execution. Never falls back to the worker."""

import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from review_snapshot import atomic_json

# Antigravity is only a reviewer; workers remain Codex or Claude Code.
PROVIDERS = ("codex", "claude", "antigravity")
DEFAULT_REVIEWER = {"codex": "claude", "claude": "codex"}
CREDENTIALS = {
    "codex": (".codex/auth.json",),
    "claude": (".claude/.credentials.json",),
    "antigravity": (".gemini/antigravity-cli/antigravity-oauth-token",
                    ".gemini/antigravity-cli/installation_id"),
}
REVIEW_HOOK = Path(__file__).resolve().with_name("review_hook.py")
IDENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
# Model names change with CLI updates, so only check that they are safe arguments.
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,127}$")
EFFORT_NAME = re.compile(r"^[a-z]{1,16}$")
MODEL_LIST_TIMEOUT = 90
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
        for p in ("invalid model selection", "not recognized as a known model", "issue with the selected model",
                  "model_not_found", "model not found", "unknown model", "invalid model",
                  "model is not supported", "does not support the model")
    ):
        return "invalid_model"
    if any(
        p in text
        for p in ("unauthorized", "authentication", "invalid api key", "login required",
                  "not logged in", "please log in", "please run /login", "invalid_grant",
                  "refresh_token_reused", "refresh_token_expired", "token_expired",
                  "token has expired", "refresh token has already been used",
                  "refresh token was already used", "refresh token has expired")
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
            provider != "claude"
            and (key.startswith("ANTHROPIC_") or key == "CLAUDE_CODE_OAUTH_TOKEN")
        ) or (
            provider != "codex"
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
        AGENTRUN_AGENT=provider,
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
        "antigravity": (".gemini/antigravity-cli/cache", ".gemini/antigravity-cli/brain"),
    }
    for relative in mounts[provider]:
        link = home / relative
        target = persisted / relative
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        link.parent.mkdir(parents=True, exist_ok=True)
        if not link.exists():
            link.symlink_to(target, target_is_directory=True)
    for relative in CREDENTIALS[provider]:
        source, target = worker_home / relative, home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        # Do not overwrite refreshed credentials in the dedicated reviewer HOME.
        if source.is_file() and not source.is_symlink() and not target.exists():
            shutil.copyfile(source, target)
            target.chmod(0o600)
    if provider == "claude":
        atomic_json(home / ".claude.json", {"hasCompletedOnboarding": True})
    if (home / CREDENTIALS[provider][0]).is_file():
        return True
    if provider == "antigravity":
        return False
    return bool(
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


def parse_models(provider, output):
    """Normalize each CLI's model list; account details and other fields are dropped."""
    models = []
    if provider == "codex":
        for item in json.loads(output)["models"]:
            if item.get("visibility") != "list":
                continue
            levels = [level["effort"] for level in item.get("supported_reasoning_levels") or []]
            models.append({"id": item["slug"], "name": item.get("display_name") or item["slug"],
                           "description": item.get("description") or "", "efforts": levels,
                           "default_effort": item.get("default_reasoning_level")})
    elif provider == "claude":
        for line in output.splitlines():
            record = json.loads(line) if line.strip().startswith("{") else None
            response = (record or {}).get("response") or {}
            if (record or {}).get("type") != "control_response" or response.get("request_id") != "agentrun-models":
                continue
            if response.get("subtype") != "success":
                raise ValueError(str(response.get("error") or "initialize failed"))
            for item in response["response"]["models"]:
                models.append({"id": item["value"], "name": item.get("displayName") or item["value"],
                               "description": item.get("description") or "",
                               "resolved": item.get("resolvedModel"),
                               "efforts": list(item.get("supportedEffortLevels") or []),
                               "default_effort": None})
            break
        else:
            raise ValueError("initialize response was not returned")
    else:
        for line in output.splitlines():
            if not line.strip():
                continue
            ident, separator, name = line.partition("\t")
            if not separator:
                raise ValueError("expected ID<TAB>name lines")
            models.append({"id": ident.strip(), "name": name.strip(), "description": "",
                           "efforts": [], "default_effort": None})
    for item in models:
        if not MODEL_NAME.fullmatch(item["id"]) or any(not EFFORT_NAME.fullmatch(e) for e in item["efforts"]):
            raise ValueError("unsafe model or effort name")
    return models


def antigravity_answer(text):
    """agy 1.4 may put the schema-checked result first in `response`; ignore the text after it."""
    if not isinstance(text, str):
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text.lstrip())
    except ValueError:
        return None
    return value


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
        self.worker_home = Path(worker_home)
        self.credential_baseline = {
            relative: (self.home / relative).read_bytes() if (self.home / relative).is_file() else None
            for relative in CREDENTIALS[provider]
        }
        self.process = None
        self.temporary = None
        self.checked = False
        # Model listing and reviews must not install or probe the CLI concurrently.
        self.setup_lock = threading.Lock()
        self.last_metadata = {}
        self.last_session_id = None
        self.last_exit_code = None
        self.input_command = None
        self.input_access = None
        self.env["UV_CACHE_DIR"] = os.environ.get(
            "UV_CACHE_DIR", str(Path(cache).parent / "uv")
        )
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
                self.temporary = Path(
                    tempfile.mkdtemp(prefix="review-codex-", dir="/tmp")
                )
                temporary.symlink_to(self.temporary)

    def adopt_credentials(self):
        # A login or import after launch updates the worker HOME; take it unless this
        # reviewer refreshed its own copy since the last synchronization.
        for relative in CREDENTIALS[self.provider]:
            source, target = self.worker_home / relative, self.home / relative
            if not source.is_file() or source.is_symlink() or target.is_symlink():
                continue
            try:
                raw = source.read_bytes()
                if raw == self.credential_baseline[relative] or not raw.strip():
                    continue
                if source.suffix == ".json":
                    value = json.loads(raw)
                    if not isinstance(value, dict) or not value:
                        continue
                current = target.read_bytes() if target.is_file() else None
                if current not in (None, self.credential_baseline[relative], raw):
                    continue  # the reviewer's own refresh is published by sync_credentials
                if current != raw:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                        temporary = Path(stream.name)
                        try:
                            os.chmod(temporary, 0o600)
                            stream.write(raw)
                            stream.flush()
                            os.replace(temporary, target)
                        finally:
                            temporary.unlink(missing_ok=True)
                self.credential_baseline[relative] = raw
            except (OSError, ValueError) as error:
                print("Reviewer credential update failed: " + str(error), file=sys.stderr)

    def sync_credentials(self):
        # Publish only refreshed credentials through the existing run-HOME sync.
        # Authentication never belongs in persisted transcript directories.
        for relative in CREDENTIALS[self.provider]:
            credential = self.home / relative
            if not credential.is_file() or credential.is_symlink():
                continue
            try:
                raw = credential.read_bytes()
                if raw == self.credential_baseline[relative] or not raw.strip():
                    continue
                if credential.suffix == ".json":
                    value = json.loads(raw)
                    if not isinstance(value, dict) or not value:
                        continue  # a partially written JSON file is checked again later
                target = self.worker_home / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
                    temporary = Path(stream.name)
                    try:
                        stream.write(raw)
                        stream.flush()
                        os.replace(temporary, target)
                        self.credential_baseline[relative] = raw
                    finally:
                        temporary.unlink(missing_ok=True)
            except (OSError, ValueError) as error:
                print("Reviewer credential synchronization failed: " + str(error), file=sys.stderr)

    def close(self):
        stop(self.process)
        self.sync_credentials()
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
                last_sync = started
                while self.process.poll() is None:
                    if time.monotonic() - last_sync >= 1:
                        self.sync_credentials()
                        last_sync = time.monotonic()
                    if cancelled.is_set():
                        raise InterruptedError("Review cancelled")
                    if timeout is not None and time.monotonic() - started > timeout:
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
                    # Antigravity reports authentication and model errors on stdout.
                    for line in (turn / "stdout.jsonl").read_text(errors="replace").splitlines()[-200:]:
                        try:
                            record = json.loads(line)
                        except ValueError:
                            continue
                        nested = record.get("result") if isinstance(record, dict) else None
                        if isinstance(record, dict) and (
                                record.get("type") in ("error", "turn.failed") or record.get("is_error")
                                or record.get("status") == "ERROR"
                                or isinstance(nested, dict) and nested.get("status") == "ERROR"):
                            diagnostic += "\n" + json.dumps(record)
                    raise ProviderError(
                        failure_kind(diagnostic),
                        f"Reviewer process failed (exit {code}); see {turn.name}/stderr.log",
                    )
            finally:
                stop(self.process)
                self.sync_credentials()
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
        with self.setup_lock:
            self.adopt_credentials()
            self._ensure(cancelled)

    def _ensure(self, cancelled):
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
                else ("--output-format", "--json-schema", "--conversation", "--settings",
                      "--disable-slash-commands", "--print-timeout", "--input-format")
                if self.provider == "antigravity"
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
                # agy prints its usage to stderr.
                help_text = (probe / "stdout.jsonl").read_text() + (probe / "stderr.log").read_text(errors="replace")
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

    def list_models(self, cancelled):
        """Return the models the installed CLI offers now; reject unexpected formats."""
        self.ensure(cancelled)
        stdin = None
        if self.provider == "codex":
            command = [self.binary, "debug", "models"]
        elif self.provider == "antigravity":
            command = [self.binary, "models"]
        else:
            # Send only the SDK initialize request; without user input no model call is made.
            command = [self.binary, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                       "--verbose", "--setting-sources", "", "--settings", str(self.home / ".claude/settings.json"),
                       "--strict-mcp-config", "--mcp-config", str(self.runtime / "empty-mcp.json"),
                       "--disable-slash-commands"]
            stdin = json.dumps({"type": "control_request", "request_id": "agentrun-models",
                                "request": {"subtype": "initialize"}}) + "\n"
        scratch = self.runtime / "scratch" / "models"
        scratch.mkdir(parents=True, exist_ok=True)
        process = subprocess.Popen(command, cwd=scratch, env=dict(self.env, CLAUDE_CODE_TMPDIR=str(scratch)),
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(stdin, timeout=MODEL_LIST_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise ProviderError("model_list_unavailable", "Model listing timed out") from error
        finally:
            stop(process)
            self.sync_credentials()
        if cancelled.is_set():
            raise InterruptedError("Model listing cancelled")
        if process.returncode:
            kind = failure_kind(stderr[-65536:] + stdout[-65536:])
            raise ProviderError(kind if kind != "provider_failed" else "model_list_unavailable",
                                f"Model listing failed (exit {process.returncode})")
        try:
            models = parse_models(self.provider, stdout)
        except (KeyError, TypeError, ValueError) as error:
            raise ProviderError("model_list_unavailable", "Unexpected model list format: " + str(error)) from error
        if not models:
            raise ProviderError("model_list_unavailable", "The CLI returned no models")
        return models

    def prepare_input_transport(self, directory, cancelled):
        if self.provider != "codex":
            return
        script = str(Path(__file__).with_name("review_inputs.py"))
        self.input_command = (
            [sys.executable, script, str(directory)]
            if importlib.util.find_spec("mcp") is not None
            else [
                "uv",
                "run",
                "--no-project",
                "--python",
                "/usr/bin/python3",
                "--with",
                "mcp==1.26.0",
                "python",
                script,
                str(directory),
            ]
        )
        check = self.runtime / "probe-inputs"
        try:
            self.execute(
                [*self.input_command, "--check"], directory, check, "", 120, cancelled
            )
            if (
                "CAPSULE_REVIEW_INPUTS_READY"
                not in (check / "stdout.jsonl").read_text()
            ):
                raise ValueError("Input reader did not confirm readiness")
        except (ProviderError, ValueError) as error:
            raise ProviderError(
                "input_reader_unavailable",
                f"Read-only input MCP failed its preflight; see {check}/stderr.log",
            ) from error
        # This diagnostic never weakens the CLI policy. MCP reads are confined
        # to the captured input even when the OS cannot create an inner sandbox.
        probe = self.runtime / "probe-sandbox"
        self.execute(
            [self.binary, "sandbox", "--help"],
            self.home,
            probe / "help",
            "",
            15,
            cancelled,
        )
        help_text = (probe / "help/stdout.jsonl").read_text()
        command = [self.binary, "sandbox"]
        if re.search(r"(?m)^\s+linux\s", help_text):
            command.append("linux")
        code = (
            "import errno, json, pathlib, sys; "
            "root=pathlib.Path(sys.argv[1]); json.loads((root/'manifest.json').read_text()); "
            "target=root/('.capsule-write-probe-' + sys.argv[2]); "
            "\ntry: target.open('x').close()"
            "\nexcept OSError as error:"
            "\n if error.errno not in (errno.EACCES, errno.EPERM, errno.EROFS): raise"
            "\n print('CAPSULE_REVIEW_SANDBOX_READ_ONLY_OK')"
            "\nelse:"
            "\n target.unlink(); raise SystemExit('Sandbox allowed writes to review inputs')\n"
        )
        command += [
            "-c",
            'sandbox_mode="read-only"',
            "--",
            sys.executable,
            "-I",
            "-c",
            code,
            str(directory),
            uuid.uuid4().hex,
        ]
        try:
            self.execute(command, directory, probe / "read", "", 15, cancelled)
            available = (
                "CAPSULE_REVIEW_SANDBOX_READ_ONLY_OK"
                in (probe / "read/stdout.jsonl").read_text()
            )
            if not available:
                raise ProviderError(
                    "sandbox_probe_failed",
                    "Sandbox probe returned no read-only confirmation",
                )
        except ProviderError as error:
            diagnostic = (probe / "read/stderr.log").read_text(errors="replace")
            if not any(
                word in diagnostic.lower()
                for word in ("bwrap:", "bubblewrap", "namespace", "unshare")
            ):
                raise ProviderError(
                    "sandbox_probe_failed",
                    f"Cannot verify the read-only sandbox; see {probe}/read/stderr.log",
                ) from error
            available = False
        self.input_access = {
            "transport": "capsule-input MCP",
            "read_only": True,
            "shell_sandbox_available": available,
            "sandbox_diagnostic": str(probe),
        }

    def turn(self, directory, prompt, schema, turn, session_id, timeout, cancelled, model=None, effort=None):
        self.last_session_id = session_id
        self.last_exit_code = None
        self.ensure(cancelled)
        schema_path = turn / "schema.json"
        turn.mkdir(parents=True, exist_ok=True)
        atomic_json(schema_path, schema)
        if session_id and not IDENT.fullmatch(session_id):
            raise ValueError("Invalid native session ID")
        if self.provider == "codex":
            if self.input_command is None:
                raise ProviderError(
                    "input_reader_unavailable", "Read-only input MCP was not prepared"
                )
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
                "mcp_servers.capsule-input.command="
                + json.dumps(self.input_command[0], ensure_ascii=False),
                "-c",
                "mcp_servers.capsule-input.args="
                + json.dumps(self.input_command[1:], ensure_ascii=False),
                "-c",
                "mcp_servers.capsule-input.startup_timeout_sec=120",
                "-c",
                "mcp_servers.capsule-input.env.UV_CACHE_DIR="
                + json.dumps(self.env["UV_CACHE_DIR"], ensure_ascii=False),
                "-c",
                "sqlite_home=" + json.dumps(str(self.home / ".codex/sqlite")),
                "-c",
                "project_doc_max_bytes=0",
                "--output-schema",
                str(schema_path),
                "-o",
                str(turn / "answer.json"),
            ]
            if model:
                command += ["--model", model]
            if effort:
                command += ["-c", "model_reasoning_effort=" + json.dumps(effort)]
            command += ["-"]
        elif self.provider == "antigravity":
            # Read only this round's input; commands, writes, URLs and MCP are denied,
            # and the PreToolUse hook rejects anything else that slips through.
            settings = {
                "toolPermission": "request-review",
                "allowNonWorkspaceAccess": False,
                "enableTerminalSandbox": True,
                "permissions": {
                    "allow": ["read_file(" + str(directory.resolve()) + ")"],
                    "deny": ["command(*)", "write_file(*)", "read_url(*)", "execute_url(*)", "mcp(*)"],
                    "ask": [],
                },
            }
            settings_path = self.home / ".gemini/antigravity-cli/settings.json"
            atomic_json(settings_path, settings)
            hook = " ".join(shlex.quote(part) for part in
                            ("/usr/bin/python3", "-Es", str(REVIEW_HOOK), str(directory.resolve())))
            atomic_json(self.home / ".gemini/config/hooks.json", {"agentrun-review": {"PreToolUse": [
                {"matcher": ".*", "hooks": [{"type": "command", "command": hook, "timeout": 30}]}]}})
            command = [self.binary, "--input-format", "stream-json", "--output-format", "stream-json",
                       "--json-schema", str(schema_path), "--settings", str(settings_path),
                       "--disable-slash-commands", "--print-timeout", "0"]
            if session_id:
                command += ["--conversation", session_id]
            if model:
                command += ["--model", model]
            if effort:
                command += ["--effort", effort]
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
            if model:
                command += ["--model", model]
            if effort:
                command += ["--effort", effort]
        cli_prompt = (json.dumps({"event": "user", "message": {"content": prompt}}) + "\n"
                      if self.provider == "antigravity" else prompt)
        elapsed = self.execute(command, directory, turn, cli_prompt, timeout, cancelled)
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
                "input_access": self.input_access,
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
        elif self.provider == "antigravity":
            records = [json.loads(line) for line in raw.splitlines() if line.strip()]
            results = [r["result"] for r in records if r.get("event") == "result" and isinstance(r.get("result"), dict)]
            if len(results) != 1:
                raise ProviderError("invalid_output_or_input", "Antigravity returned no unique final result")
            envelope = results[0]
            native = envelope.get("conversation_id")
            if isinstance(native, str) and IDENT.fullmatch(native):
                self.last_session_id = native
            if envelope.get("status") != "SUCCESS":
                raise ProviderError(failure_kind(str(envelope.get("error", ""))),
                                    "Antigravity did not complete its turn")
            ident = native
            result = envelope.get("structured_output")
            if result is None:
                result = antigravity_answer(envelope.get("response"))
            if not isinstance(result, dict):
                raise ProviderError("invalid_output_or_input", "Antigravity returned no structured result")
            metadata = {key: envelope.get(key) for key in ("model", "usage", "duration_seconds", "num_turns")}
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
                # The final envelope names the resolved model only through modelUsage.
                "model": envelope.get("model") or next(iter(envelope.get("modelUsage") or {}), None),
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
