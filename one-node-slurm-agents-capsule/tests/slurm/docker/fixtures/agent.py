#!/usr/bin/env python3
"""Offline CLI boundary with native transcripts; never calls a model service."""

import json
import os
import signal
import socket
import sys
import time
import tomllib
import tty
import uuid
from pathlib import Path

AGENT = Path(sys.argv[0]).name
ARGS = sys.argv[1:]
assert AGENT in ("codex", "claude"), AGENT
HOME = Path.home()
CREDENTIAL = HOME / (
    ".codex/auth.json" if AGENT == "codex" else ".claude/.credentials.json"
)


def transcript(ident, prompt, answer):
    if AGENT == "codex":
        path = HOME / f".codex/sessions/2026/10/21/rollout-{ident}.jsonl"
        records = [
            {
                "type": "session_meta",
                "payload": {"id": ident, "cwd": str(Path.cwd()), "source": "cli"},
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": prompt}],
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "fixture-command",
                    "arguments": json.dumps({"cmd": "printf offline-output"}),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "fixture-command",
                    "output": "offline-output",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": answer}],
                },
            },
        ]
    else:
        path = HOME / f".claude/projects/-workspace/{ident}.jsonl"
        records = [
            {
                "sessionId": ident,
                "cwd": str(Path.cwd()),
                "type": "user",
                "message": {"role": "user", "content": prompt},
            },
            {
                "sessionId": ident,
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "fixture-command",
                            "name": "Bash",
                            "input": {"command": "printf offline-output"},
                        }
                    ],
                },
            },
            {
                "sessionId": ident,
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "fixture-command",
                            "content": "offline-output",
                        }
                    ],
                },
            },
            {
                "sessionId": ident,
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": answer}],
                },
            },
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.writelines(json.dumps(entry) + "\n" for entry in records)
    return path


if ARGS == ["login"] or ARGS == ["auth", "login"]:
    assert Path("/etc/capsule-test-cluster").exists()
    CREDENTIAL.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIAL.write_text('{"synthetic":"offline-login"}')
    CREDENTIAL.chmod(0o600)
    if AGENT == "claude":
        (HOME / ".claude.json").write_text('{"hasCompletedOnboarding":true}')
        (HOME / ".claude.json").chmod(0o600)
    print("SYNTHETIC_LOGIN_OK")
    raise SystemExit(0)

if AGENT == "codex":
    temporary = HOME / ".codex/tmp"
    assert temporary.is_symlink() and temporary.is_dir(), temporary
    assert temporary.stat().st_dev == Path("/tmp").stat().st_dev
    assert temporary.stat().st_dev != HOME.stat().st_dev
    assert temporary.stat().st_mode & 0o777 == 0o700
if ARGS == ["--version"]:
    print(f"{AGENT} capsule-test-1")
    raise SystemExit(0)
if "--help" in ARGS:
    print(
        "--json --output-schema --ignore-user-config --ignore-rules --restricted --safe-mode "
        "--tools --strict-mcp-config --permission-prompts --json-schema"
    )
    raise SystemExit(0)

if os.environ.get("AGENTRUN_ROLE") == "reviewer":
    assert "AGENT_REVIEW_SOCKET" not in os.environ
    assert not any("bypass" in value for value in ARGS)
    assert CREDENTIAL.is_file()
    if AGENT == "codex":
        assert 'sandbox_mode="read-only"' in ARGS
    else:
        assert ARGS[ARGS.index("--tools") + 1] == "Read,Glob,Grep"
        assert "--safe-mode" in ARGS and "--restricted" in ARGS
    context = json.loads(sys.stdin.read().split("\n", 1)[1])
    mode = next(p.read_text().strip() for p in Path("brief").rglob("*") if p.is_file())
    ident = (
        ARGS[ARGS.index("resume") + 1]
        if "resume" in ARGS
        else ARGS[ARGS.index("--resume") + 1]
        if "--resume" in ARGS
        else str(uuid.uuid4())
    )
    result = {
        "kind": "review_result",
        "target_id": context["target_id"],
        "summary": "offline reviewed",
        "verdict": "approve",
        "coverage": "complete",
        "limitations": [],
        "questions": [],
        "findings": [],
        "prior_dispositions": [],
        "praise": [],
        "checked_scope": ["source/code.py"],
    }
    if mode == "timeout":
        while True:
            time.sleep(1)
    if context["round"] == 1 and context["message"] is None and context["dialogue"]:
        result.update(
            kind="question",
            verdict="none",
            questions=[
                {
                    "question_id": "q1",
                    "text": "Why this value?",
                    "evidence": ["source/code.py"],
                }
            ],
        )
    elif context["round"] == 1 and mode == "question-finding":
        result.update(
            verdict="request_changes",
            findings=[
                {
                    "finding_id": "f1",
                    "severity": "major",
                    "confidence": "high",
                    "basis": "observed",
                    "evidence_method": "static_source",
                    "file": "source/code.py",
                    "line": 1,
                    "message": "A fixture defect",
                    "suggestion": "Change value to 2",
                    "evidence": ["source/code.py"],
                }
            ],
        )
    if context["round"] == 2:
        prior = json.loads(Path("prior/review.json").read_text())
        assert prior["response"]["responses"][0]["action"] == "fixed"
        assert Path("source/code.py").read_text() == "value = 2\n"
        result["prior_dispositions"] = [
            {
                "finding_id": "f1",
                "status": "resolved",
                "reason": "Checked changed source",
                "evidence": ["source/code.py"],
            }
        ]
    transcript(ident, "offline reviewer turn", json.dumps(result))
    persisted = (
        (HOME / (".codex/sessions" if AGENT == "codex" else ".claude/projects"))
        .resolve()
        .parents[1]
    )
    with (persisted / "fixture-calls.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"session": ident, "args": ARGS, "round": context["round"]})
            + "\n"
        )
    if AGENT == "codex":
        Path(ARGS[ARGS.index("-o") + 1]).write_text(json.dumps(result))
        print(json.dumps({"type": "thread.started", "thread_id": ident}))
        print(json.dumps({"type": "turn.completed"}))
    else:
        print(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "is_error": False,
                    "session_id": ident,
                    "structured_output": result,
                }
            )
        )
    raise SystemExit(0)

assert Path("/workspace").is_dir() and os.getuid() == 1000
assert os.environ.get("AGENTRUN_ROLE") == "worker"
assert os.environ["SLURMD_NODENAME"] == "compute"
assert len(os.sched_getaffinity(0)) == int(os.environ["SLURM_CPUS_PER_TASK"]) == 1
assert not any(key in os.environ for key in ("GH_TOKEN", "GITHUB_TOKEN"))
assert CREDENTIAL.is_file(), CREDENTIAL
assert "nameserver" in Path("/etc/resolv.conf").read_text()
socket.getaddrinfo("controller", 6817)
if AGENT == "codex":
    config = tomllib.loads((HOME / ".codex/config.toml").read_text())
    assert "cross-review" in config["mcp_servers"]
    tomllib.loads(Path("/etc/codex/requirements.toml").read_text())
else:
    json.loads((HOME / ".claude/settings.json").read_text())
    mcp = json.loads(Path("/runs/container_config/review-mcp.json").read_text())
    assert "cross-review" in mcp["mcpServers"]
print("CONFIG_AND_DNS_OK", flush=True)
scenario = Path("/workspace/.capsule-test.json")
options = json.loads(scenario.read_text()) if scenario.exists() else {}
sys.path.insert(0, "/opt/capsule-test")
from features import check_features

check_features(AGENT, options)

ident = (
    ARGS[ARGS.index("resume") + 1]
    if "resume" in ARGS
    else ARGS[ARGS.index("--resume") + 1]
    if "--resume" in ARGS
    else str(uuid.uuid4())
)
resumed = "resume" in ARGS or "--resume" in ARGS
if resumed:
    roots = HOME / (".codex/sessions" if AGENT == "codex" else ".claude/projects")
    assert any(
        ident in str(p) and "capsule persisted conversation" in p.read_text()
        for p in roots.rglob("*.jsonl")
    ), "resume lost native history"
transcript(ident, "offline fixture user", "capsule persisted conversation")
Path("/runs/artifacts/report.md").write_text(
    "# Offline fixture report\n\nCompleted fixture work.\n"
)
Path("/runs/artifacts/run_title.txt").write_text(
    "completed isolated cluster fixture work\n"
)
print(("RESUME_OK:" if resumed else "AGENT_READY:") + AGENT + ":" + ident, flush=True)
if options.get("hold"):
    if os.isatty(0):
        tty.setraw(0)
        os.write(1, b"\x1b[?1003h\x1b[?1006h\x1b[?2004h\x1b[>17u")
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
raise SystemExit(options.get("exit_code", 0))
