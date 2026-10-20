"""Assertions executed inside real capsules, rather than inferred from plans."""

import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def execute(args, expected=0, **kwargs):
    result = subprocess.run(
        args, check=False, capture_output=True, text=True, timeout=35, **kwargs
    )
    assert result.returncode == expected, (
        args,
        result.returncode,
        result.stdout,
        result.stderr,
    )
    return result


def check_features(agent, options):
    hooks = Path("/home/sandbox/ai-agent-config/common/hooks")
    skills = Path("/home/sandbox/ai-agent-config/common/skills")
    assert (skills / "cross-review/SKILL.md").is_file()
    assert (skills / "research-latex/SKILL.md").is_file()
    for path in (skills / "cross-review/SKILL.md", hooks / "worker_hook.py"):
        try:
            with path.open("a") as stream:
                stream.write("forbidden")
        except OSError:
            pass
        else:
            raise AssertionError(f"configuration is writable: {path}")
    Path("/workspace/workspace-write.txt").write_text("workspace is writable")
    assert Path("/scratch").samefile("/runs/scratch")
    if options.get("ssd", True):
        assert os.environ["AGENTRUN_NODE_SCRATCH"] == "/node-scratch"
        assert Path("/node-scratch/node-marker.txt").read_text() == "node-local SSD\n"
        Path("/node-scratch/fixture-write.txt").write_text("SSD data")
    else:
        assert os.environ["AGENTRUN_NODE_SCRATCH"] == ""
    for mount in options.get("mounts", []):
        path = Path(mount["path"])
        assert (path / "source.txt").read_text() == "host data"
        try:
            (path / "written.txt").write_text("container data")
        except OSError:
            assert not mount["writable"]
        else:
            assert mount["writable"]
    if options.get("secrets"):
        assert os.environ["HF_TOKEN"] == "CAPSULE_SYNTHETIC_HF_TOKEN"
    if options.get("hooks"):
        for script, command in (
            ("check_pip_forbidden.py", "pip install x"),
            ("check_sbatch_forbidden.py", "sbatch x.sh"),
            ("git_branch_guard.py", "git push"),
            ("block_dangerous_command.py", "cat ~/.ssh/id_rsa"),
        ):
            payload = json.dumps(
                {"tool_name": "Bash", "tool_input": {"command": command}}
            )
            execute(["python3", str(hooks / script)], expected=2, input=payload)
        payload = json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "git status"}}
        )
        execute(["python3", str(hooks / "block_dangerous_command.py")], input=payload)
        execute(["python3", str(hooks / "update_run_status.py")], input=payload)
        assert "git status" in Path("/runs/live/command_log.jsonl").read_text()
        if agent == "claude":
            execute(["bash", str(Path.home() / ".claude/statusline.sh")], input="{}")
    if options.get("gh"):
        result = execute(
            ["gh", "issue", "view", "1", "--repo", "owner/repo", "--json", "title"]
        )
        assert "GITHUB_BOUNDARY_OK" in result.stdout
        assert "CAPSULE_DOCKER_SYNTHETIC_TOKEN" not in result.stdout + result.stderr
        for args in (
            ["api", "user"],
            ["issue", "view", "1", "--repo", "other/repo", "--json", "title"],
        ):
            rejected = subprocess.run(
                ["gh", *args], check=False, capture_output=True, text=True, timeout=15
            )
            assert rejected.returncode != 0, rejected
    if options.get("review"):
        # Seed the exact production uv command's dependency cache; runtime has
        # no external network and uses the real uv executable and MCP SDK.
        shutil.copytree("/opt/test-uv-cache", "/cache/uv", dirs_exist_ok=True)
        os.environ["UV_OFFLINE"] = "1"
        sys.path.insert(0, "/opt/test-deps/lib/python3.12/site-packages")
        asyncio.run(review_dialogue(options["review"]))
    if options.get("review_negative"):
        brief = Path("/runs/artifacts/negative-brief.md")
        brief.write_text(options["review_negative"])
        state = json.loads(
            execute(
                [
                    "/opt/agentrun/agent-review",
                    "run",
                    "--request-id",
                    "negative",
                    "--one-shot",
                    "--wait",
                    "--brief",
                    str(brief),
                ]
            ).stdout
        )
        if options["review_negative"] == "missing-auth":
            assert state["status"] == "failed" and "authentication" in json.dumps(
                state
            ), state
        else:
            assert state["status"] == "timeout", state
            for process in Path("/proc").iterdir():
                try:
                    args = (process / "cmdline").read_bytes()
                except (FileNotFoundError, PermissionError, NotADirectoryError):
                    continue
                assert b"/cache/review-cli/" not in args, args
        Path("/runs/artifacts/negative-review.json").write_text(json.dumps(state))
    Path("/runs/artifacts/feature-checks.json").write_text(json.dumps(options))
    print("FEATURE_CHECKS_OK", flush=True)


async def review_dialogue(transport):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    brief = Path("/runs/artifacts/brief.md")
    brief.write_text("question-finding")
    command = "/opt/agentrun/agent-review"

    def cli(*args):
        return json.loads(execute([command, *args]).stdout)

    async def run(session=None):
        async def action(name, **params):
            value = await session.call_tool(name, params)
            assert not value.isError, value
            return value.structuredContent or json.loads(value.content[0].text)

        if session:
            await session.initialize()
            tools = await session.list_tools()
            assert {t.name for t in tools.tools} == {
                "review_start",
                "review_reply",
                "review_recheck",
                "review_events",
                "review_status",
                "review_cancel",
                "review_extend",
            }
            state = await action("review_start", request_id="initial", brief=str(brief))
        else:
            state = cli("run", "--request-id", "initial", "--brief", str(brief))
        ident = state["review_id"]
        for _ in range(50):
            state = cli(
                "events", ident, "--after", str(state["cursor"]), "--wait-seconds", "1"
            )
            if state["status"] == "waiting_reply":
                break
        assert state["status"] == "waiting_reply", state
        answer = {
            "answers": [
                {
                    "question_id": "q1",
                    "answer": "Fixture value",
                    "evidence": ["source/code.py"],
                }
            ],
            "questions": [],
            "include": [],
        }
        reply = Path("/runs/artifacts/answer.json")
        reply.write_text(json.dumps(answer))
        cli(
            "reply",
            ident,
            "--request-id",
            "answer",
            "--reply-to",
            state["question"]["message_id"],
            "--message-file",
            str(reply),
        )
        state = cli("status", ident)
        for _ in range(50):
            state = cli(
                "events", ident, "--after", str(state["cursor"]), "--wait-seconds", "1"
            )
            if state["status"] not in ("prepared", "running"):
                break
        assert state["status"] == "success" and state["verdict"] == "request_changes", (
            state
        )
        Path("/workspace/code.py").write_text("value = 2\n")
        response = {
            "responses": [
                {
                    "finding_id": "f1",
                    "action": "fixed",
                    "reason": "Changed value",
                    "evidence": ["source/code.py"],
                }
            ]
        }
        file = Path("/runs/artifacts/response.json")
        file.write_text(json.dumps(response))
        if session:
            state = await action(
                "review_recheck",
                review_id=ident,
                request_id="recheck",
                response=response,
            )
        else:
            state = cli(
                "recheck", ident, "--request-id", "recheck", "--response", str(file)
            )
        previous = ident
        ident = state["review_id"]
        assert ident != previous and state["round"] == 2, state
        for _ in range(50):
            state = cli(
                "events", ident, "--after", str(state["cursor"]), "--wait-seconds", "1"
            )
            if state["status"] not in ("prepared", "running"):
                break
        assert state["status"] == "success" and state["verdict"] == "approve", state
        if session:
            via_mcp = await action("review_status", review_id=ident)
            assert via_mcp["verdict"] == "approve"
        result = Path("/runs/artifacts/dialogue-check.json")
        result.write_text(json.dumps(state))
        third_response = Path("/runs/artifacts/third-response.json")
        third_response.write_text('{"responses":[]}')
        rejected = await asyncio.to_thread(
            subprocess.run,
            [
                command,
                "recheck",
                ident,
                "--request-id",
                "third",
                "--response",
                str(third_response),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert rejected.returncode != 0, rejected
        assert "budget exhausted" in rejected.stderr, rejected
        print("CROSS_REVIEW_OK:" + transport, flush=True)

    if transport == "mcp":
        env = dict(os.environ)
        params = StdioServerParameters(command=command, args=["mcp"], env=env)
        async with stdio_client(params) as (reader, writer):  # noqa: SIM117 -- streams initialize ClientSession
            async with ClientSession(reader, writer) as session:
                await run(session)
    else:
        await run()
