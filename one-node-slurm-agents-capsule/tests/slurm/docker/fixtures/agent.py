#!/usr/bin/env python3
"""Offline CLI boundary with native transcripts; never calls a model service."""

import json
import os
import re
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
assert AGENT in ("codex", "claude", "agy"), AGENT
# agentrun's name for the agent; Antigravity's CLI is called agy.
PROVIDER = "antigravity" if AGENT == "agy" else AGENT
HOME = Path.home()
AGY = HOME / ".gemini/antigravity-cli"
CREDENTIAL = HOME / {
    "codex": ".codex/auth.json",
    "claude": ".claude/.credentials.json",
    "agy": ".gemini/antigravity-cli/antigravity-oauth-token",
}[AGENT]
# Where each CLI keeps native conversations (agy: one brain/<id> directory each).
NATIVE = {"codex": HOME / ".codex/sessions", "claude": HOME / ".claude/projects", "agy": AGY / "brain"}[AGENT]


def option(*names):
    return next((ARGS[ARGS.index(name) + 1] for name in names if name in ARGS), None)


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
    elif AGENT == "agy":
        # agy 1.5: steps in conversations/<id>.db, the readable log in brain/<id>/.
        path = AGY / "brain" / ident / ".system_generated/logs/transcript.jsonl"
        start = len(path.read_text().splitlines()) if path.exists() else 0
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        records = [
            {"step_index": start, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": stamp, "content": f"<USER_REQUEST>\n{prompt}\n</USER_REQUEST>"},
            {"step_index": start + 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": stamp, "thinking": "fixture thought",
             "tool_calls": [{"name": "run_command", "args": {"CommandLine": "printf offline-output"}}]},
            {"step_index": start + 2, "source": "MODEL", "type": "GENERIC", "status": "DONE",
             "created_at": stamp, "content": "offline-output"},
            {"step_index": start + 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": stamp, "content": answer},
        ]
        (AGY / "conversations").mkdir(parents=True, exist_ok=True)
        (AGY / "conversations" / f"{ident}.db").touch()
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


if AGENT == "agy" and ARGS == [] and "AGENTRUN_ROLE" not in os.environ:
    # agy has no login subcommand: agentrun opens it, and you sign in on its first screen.
    assert Path("/etc/capsule-test-cluster").exists()
    CREDENTIAL.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIAL.write_text('{"synthetic":"offline-login"}')
    CREDENTIAL.chmod(0o600)
    (AGY / "installation_id").write_text("offline-installation\n")
    print("SYNTHETIC_LOGIN_OK")
    raise SystemExit(0)

if ARGS in (["login"], ["login", "--device-auth"], ["auth", "login"]):
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
        "--tools --strict-mcp-config --permission-prompts --json-schema",
        # agy prints its usage to stderr.
        file=sys.stderr if AGENT == "agy" else sys.stdout,
    )
    if AGENT == "agy":
        print("--output-format --conversation --settings --disable-slash-commands --print-timeout "
              "--input-format", file=sys.stderr)
    raise SystemExit(0)

if ARGS and ARGS[0] == "sandbox":
    assert 'sandbox_mode="read-only"' in ARGS
    print("CAPSULE_REVIEW_SANDBOX_READ_ONLY_OK")
    raise SystemExit(0)

if os.environ.get("AGENTRUN_ROLE") == "reviewer" and (
        ARGS[:2] == ["debug", "models"] or ARGS == ["models"]
        or (AGENT == "claude" and "--input-format" in ARGS)):
    # Reproduce each CLI's model list format without calling a model service.
    if AGENT == "agy":
        print("fixture-review-model\tFixture")
    elif AGENT == "codex":
        print(json.dumps({"models": [{"slug": "fixture-review-model", "display_name": "Fixture", "visibility": "list",
                                      "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]}]}))
    else:
        request = json.loads(sys.stdin.readline())
        assert request["request"]["subtype"] == "initialize"
        print(json.dumps({"type": "control_response", "response": {
            "subtype": "success", "request_id": request["request_id"],
            "response": {"models": [{"value": "fixture-review-model", "displayName": "Fixture",
                                     "supportedEffortLevels": ["low", "high"]}]}}}))
    raise SystemExit(0)

if os.environ.get("AGENTRUN_ROLE") == "reviewer":
    assert "AGENT_REVIEW_SOCKET" not in os.environ
    assert not any("bypass" in value for value in ARGS)
    assert CREDENTIAL.is_file()
    if AGENT == "codex":
        assert 'sandbox_mode="read-only"' in ARGS
        assert any(a.startswith("mcp_servers.capsule-input.command=") for a in ARGS)
    elif AGENT == "agy":
        settings = json.loads(Path(option("--settings")).read_text())
        assert "command(*)" in settings["permissions"]["deny"], settings
        assert "review_hook.py" in (HOME / ".gemini/config/hooks.json").read_text()
        assert "--json-schema" in ARGS and option("--input-format") == "stream-json"
    else:
        assert ARGS[ARGS.index("--tools") + 1] == "Read,Glob,Grep"
        assert "--safe-mode" in ARGS and "--restricted" in ARGS
    raw = sys.stdin.read()
    if AGENT == "agy":  # one stream-json user event carries the prompt
        raw = json.loads(raw.splitlines()[0])["message"]["content"]
    context = json.loads(raw.split("\n", 1)[1])
    mode = next(p.read_text().strip() for p in Path("brief").rglob("*") if p.is_file())
    ident = (
        ARGS[ARGS.index("resume") + 1]
        if "resume" in ARGS
        else option("--resume", "--conversation") or str(uuid.uuid4())
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
    if context["round"] >= 3:
        prior = json.loads(Path("prior/review.json").read_text())
        assert prior["response"]["responses"] == []
        assert Path("source/code.py").read_text() == f"value = {context['round']}\n"
    transcript(ident, "offline reviewer turn", json.dumps(result))
    persisted = NATIVE.resolve().parents[2 if AGENT == "agy" else 1]
    with (persisted / "fixture-calls.jsonl").open("a") as stream:
        stream.write(
            json.dumps({"session": ident, "args": ARGS, "round": context["round"]})
            + "\n"
        )
    if AGENT == "codex":
        Path(ARGS[ARGS.index("-o") + 1]).write_text(json.dumps(result))
        print(json.dumps({"type": "thread.started", "thread_id": ident}))
        print(json.dumps({"type": "turn.completed"}))
    elif AGENT == "agy":
        print(json.dumps({"event": "init", "conversation_id": ident, "init": {"cwd": str(Path.cwd())}}))
        print(json.dumps({"event": "result", "result": {"conversation_id": ident, "status": "SUCCESS",
                                                        "structured_output": result}}))
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
    config_path = HOME / ".codex/config.toml"
    config_text = config_path.read_text()
    config = tomllib.loads(config_text)
    assert "cross-review" in config["mcp_servers"]
    tomllib.loads(Path("/etc/codex/requirements.toml").read_text())
    effort = "low" if config.get("model_reasoning_effort") != "low" else "high"
    setting = f'model_reasoning_effort = "{effort}"'
    if "model_reasoning_effort" in config:
        config_text = re.sub(
            r"(?m)^model_reasoning_effort\s*=.*$", setting, config_text, count=1
        )
    else:
        config_text = setting + "\n" + config_text
    temporary = config_path.with_name("config.toml.tmp.capsule-test")
    temporary.write_text(config_text)
    temporary.replace(config_path)
elif AGENT == "agy":
    settings_path = AGY / "settings.json"
    settings = json.loads(settings_path.read_text())
    original = json.loads(Path("/runs/container_config/settings.json").read_text())
    assert settings == original
    assert settings["toolPermission"] == "always-proceed"
    assert "--dangerously-skip-permissions" in ARGS
    hooks = json.loads((HOME / ".gemini/config/hooks.json").read_text())
    assert "worker_hook.py --antigravity PreToolUse" in json.dumps(hooks)
    assert (HOME / ".gemini/GEMINI.md").read_text().strip(), "the shared rules reach agy"
    assert (HOME / ".gemini/config/skills/cross-review/SKILL.md").is_file()
    assert json.loads((AGY / "cache/onboarding.json").read_text())["onboardingComplete"]
    mcp = json.loads((HOME / ".gemini/config/mcp_config.json").read_text())
    assert mcp["mcpServers"]["cross-review"]["env"]["AGENT_REVIEW_SOCKET"], mcp
    # Exercise the atomic rewrite agy uses when /model saves the choice.
    settings["model"] = "Fixture B" if settings.get("model") == "Fixture A" else "Fixture A"
    temporary = settings_path.with_name("settings.json.tmp.capsule-test")
    temporary.write_text(json.dumps(settings) + "\n")
    temporary.replace(settings_path)
    assert json.loads(Path("/runs/container_config/settings.json").read_text()) == original
    print("ANTIGRAVITY_SETTINGS_ATOMIC_SAVE_OK", flush=True)
else:
    settings_path = HOME / ".claude/settings.json"
    settings = json.loads(settings_path.read_text())
    original = json.loads(Path("/runs/container_config/settings.json").read_text())
    assert settings == original
    # Exercise the real atomic rename used by Claude's /effort settings save.
    settings["effortLevel"] = (
        "medium" if settings.get("effortLevel") != "medium" else "high"
    )
    temporary = settings_path.with_name("settings.json.tmp.capsule-test")
    temporary.write_text(json.dumps(settings) + "\n")
    temporary.replace(settings_path)
    assert json.loads(settings_path.read_text()) == settings
    assert (
        json.loads(Path("/runs/container_config/settings.json").read_text()) == original
    )
    print("CLAUDE_SETTINGS_ATOMIC_SAVE_OK", flush=True)
    mcp = json.loads(Path("/runs/container_config/review-mcp.json").read_text())
    assert "cross-review" in mcp["mcpServers"]
print("CONFIG_AND_DNS_OK", flush=True)
scenario = Path("/workspace/.capsule-test.json")
options = json.loads(scenario.read_text()) if scenario.exists() else {}
sys.path.insert(0, "/opt/capsule-test")
from features import check_features

check_features(PROVIDER, options)

ident = (
    ARGS[ARGS.index("resume") + 1]
    if "resume" in ARGS
    else option("--resume", "--conversation") or str(uuid.uuid4())
)
resumed = "resume" in ARGS or "--resume" in ARGS or "--conversation" in ARGS
if resumed:
    assert any(
        ident in str(p) and "capsule persisted conversation" in p.read_text()
        for p in NATIVE.rglob("*.jsonl")
    ), "resume lost native history"
transcript(ident, "offline fixture user", "capsule persisted conversation")
Path("/runs/artifacts/report.md").write_text(
    "# Offline fixture report\n\nCompleted fixture work.\n"
)
Path("/runs/artifacts/run_title.txt").write_text(
    "completed isolated cluster fixture work\n"
)
print(("RESUME_OK:" if resumed else "AGENT_READY:") + PROVIDER + ":" + ident, flush=True)
if options.get("hold"):
    if os.isatty(0):
        tty.setraw(0)
        os.write(1, b"\x1b[?1003h\x1b[?1006h\x1b[?2004h\x1b[>17u")
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    while True:
        time.sleep(1)
raise SystemExit(options.get("exit_code", 0))
