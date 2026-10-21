#!/usr/bin/env python3
"""Supervise the worker and its run-scoped review service inside the capsule."""

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from review import Reviews
from review_snapshot import atomic_json, git


def update_codex_mcp_environment(path, environment):
    """Replace per-allocation connection settings without duplicating TOML tables."""
    text = path.read_text()
    document = tomllib.loads(text)
    current = document.get("mcp_servers", {}).get("cross-review", {}).get("env", {})
    values = {**current, **environment}
    if any(not isinstance(value, str) for value in values.values()):
        raise ValueError("Cross-review MCP environment values must be strings")

    def complete_prefix(offset):
        try:
            tomllib.loads(text[:offset])
            return True
        except tomllib.TOMLDecodeError:
            return False

    # A line resembling a header may be inside a multiline string or array.
    # Let the TOML parser distinguish it, and retain array tables as boundaries.
    headers = [
        header
        for header in re.finditer(
            r"(?m)^[ \t]*\[[^\n]+\][ \t]*(?:#[^\n]*)?(?:\n|$)", text
        )
        if complete_prefix(header.start())
    ]
    env_span = parent_span = None
    for index, header in enumerate(headers):
        if header.group().lstrip().startswith("[["):
            continue
        parsed = tomllib.loads(header.group())
        server = parsed.get("mcp_servers", {}).get("cross-review", {})
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        if server == {"env": {}}:
            env_span = (header.start(), end)
            break
        if server == {} and "cross-review" in parsed.get("mcp_servers", {}):
            parent_span = (header.end(), end)
    if env_span:
        text = text[: env_span[0]] + text[env_span[1] :]
    elif parent_span:
        # TOML permits an inline env table or dotted env keys in the parent.
        start, end = parent_span
        body = text[start:end]
        assignments = list(
            re.finditer(
                r"(?m)^[ \t]*(?:env|\"env\"|'env')(?:\.[^=\n]+)?[ \t]*=[^\n]*(?:\n|$)",
                body,
            )
        )
        for assignment in reversed(assignments):
            if not complete_prefix(start + assignment.start()):
                continue
            stop = assignment.end()
            while stop < len(body) and not complete_prefix(start + stop):
                newline = body.find("\n", stop)
                stop = newline + 1 if newline >= 0 else len(body)
            body = body[: assignment.start()] + body[stop:]
        text = text[:start] + body + text[end:]
    text = text.rstrip() + "\n\n[mcp_servers.cross-review.env]\n"
    text += "".join(
        json.dumps(key, ensure_ascii=False)
        + " = "
        + json.dumps(value, ensure_ascii=False)
        + "\n"
        for key, value in values.items()
    )
    tomllib.loads(text)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=("codex", "claude"))
    parser.add_argument("--run-dir", type=Path, default=Path("/runs"))
    parser.add_argument("--workspace", type=Path, default=Path("/workspace"))
    parser.add_argument(
        "--reviewer-store", type=Path, default=Path("/reviewer-sessions")
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("/cache"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    run, repo = args.run_dir.resolve(), args.workspace.resolve()
    runtime_source = Path(__file__).resolve().parent
    runtime = Path(tempfile.mkdtemp(prefix="agentrun-review-", dir="/tmp"))
    endpoint = runtime / "review.sock"
    env = dict(
        os.environ,
        AGENT_REVIEW_SOCKET=str(endpoint),
        AGENTRUN_ROLE="worker",
        UV_CACHE_DIR=str(args.cache_dir / "uv"),
        PATH=str(runtime_source) + ":" + os.environ["PATH"],
    )
    env.setdefault("MCP_TIMEOUT", "120000")
    try:
        baseline = {
            "head": git(repo, "rev-parse", "HEAD"),
            "status": git(repo, "status", "--porcelain=v1", "-z", binary=True).decode(),
            "recorded_at": time.time(),
        }
    except subprocess.SubprocessError:
        baseline = {
            "head": None,
            "status": None,
            "recorded_at": time.time(),
            "error": "No committed Git repository; review requires an explicit committed base",
        }
    atomic_json(run / "reviews/worker-start.json", baseline)
    atomic_json(
        run / "reviews/auth-readiness.json",
        {
            "codex": (Path.home() / ".codex/auth.json").is_file()
            or bool(env.get("OPENAI_API_KEY") or env.get("CODEX_API_KEY")),
            "claude": (Path.home() / ".claude/.credentials.json").is_file()
            or bool(
                env.get("ANTHROPIC_API_KEY")
                or env.get("ANTHROPIC_AUTH_TOKEN")
                or env.get("CLAUDE_CODE_OAUTH_TOKEN")
            ),
        },
    )
    session = json.loads((run / "session.json").read_text())
    config = {
        "run": str(run),
        "repo": str(repo),
        "primary_agent": args.agent,
        "worker_home": str(Path.home()),
        "reviewer_store": str(args.reviewer_store.resolve()),
        "installer": str(runtime_source / "install-agent.sh"),
        "cache": str(args.cache_dir / "review-cli"),
        "baseline": baseline,
        "mode": session["mode"],
        "run_id": session.get("run_id", run.name),
        "session_key": session.get("session_key"),
    }
    for key in ("model", "effort"):
        # Settings refer to the reviewer provider, not the worker provider.
        peer = "CODEX" if args.agent == "claude" else "CLAUDE"
        value = os.environ.get("AGENT_REVIEW_" + peer + "_" + key.upper())
        if value:
            config[key] = value
    for key in ("max_exchanges", "active_timeout", "reply_timeout", "thread_timeout"):
        if os.environ.get("AGENT_REVIEW_" + key.upper()):
            config[key] = int(os.environ["AGENT_REVIEW_" + key.upper()])
    if os.environ.get("SLURM_JOB_END_TIME"):
        config["job_deadline"] = float(os.environ["SLURM_JOB_END_TIME"])
    mcp_environment = {
        "AGENT_REVIEW_SOCKET": str(endpoint),
        "UV_CACHE_DIR": str(args.cache_dir / "uv"),
    }
    mcp_config = {
        "mcpServers": {
            "cross-review": {
                "command": str(runtime_source / "agent-review"),
                "args": ["mcp"],
                "env": mcp_environment,
            }
        }
    }
    atomic_json(run / "container_config/review-mcp.json", mcp_config)
    if args.agent == "codex":
        update_codex_mcp_environment(
            Path.home() / ".codex/config.toml", mcp_environment
        )
    atomic_json(runtime / "config.json", config)
    # Detached helpers must never inherit the worker's terminal streams.
    # Their diagnostics can arrive after the foreground UI or srun has exited.
    service_log = run / "live/review_service.log"
    service_log.parent.mkdir(parents=True, exist_ok=True)
    with service_log.open("a") as log:
        service = subprocess.Popen(
            [
                sys.executable,
                str(runtime_source / "review.py"),
                str(runtime / "config.json"),
                str(endpoint),
            ],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    worker = None
    interrupted = [None]

    def interrupted_handler(signum, _frame):
        # A terminal interrupt is already delivered to the foreground worker.
        # Keep the service alive while the CLI handles its normal Ctrl+C UI.
        if signum == signal.SIGINT and sys.stdin.isatty():
            return
        interrupted[0] = signum
        if worker and worker.poll() is None:
            worker.send_signal(signum)

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, interrupted_handler)
    try:
        deadline = time.monotonic() + 10
        while not endpoint.exists():
            if (
                service.poll() is not None
                or time.monotonic() > deadline
                or interrupted[0]
            ):
                raise RuntimeError(f"Review service failed to start; see {service_log}")
            time.sleep(0.05)
        worker = subprocess.Popen(command, env=env)
        while worker.poll() is None:
            if interrupted[0] is not None:
                try:
                    worker.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    worker.kill()
            time.sleep(0.05)
        return worker.returncode if worker.returncode >= 0 else 128 - worker.returncode
    finally:
        service.terminate()
        try:
            service.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(service.pid, signal.SIGKILL)
            service.wait(timeout=2)
        # Recover recorded children and incomplete states even if the service
        # was SIGKILLed and could not run its own finally block.
        Reviews(config).close()
        shutil.rmtree(runtime, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
