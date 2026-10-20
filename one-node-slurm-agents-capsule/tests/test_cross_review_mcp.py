"""Real MCP stdio framing and CLI interoperation, with fake provider processes."""

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest

import test_cross_review as fixtures


@unittest.skipUnless(
    importlib.util.find_spec("mcp"), "Run with uv --with mcp==1.26.0 for real MCP tests"
)
class MCPReviewTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CrossReviewTests(
            "test_idempotency_and_stale_question_rejection"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.endpoint = self.fixture.root / "service.sock"
        config = self.fixture.root / "service.json"
        config.write_text(json.dumps(self.fixture.config))
        self.service = subprocess.Popen(
            [
                sys.executable,
                str(fixtures.RUNTIME / "review.py"),
                str(config),
                str(self.endpoint),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.stop_service)
        deadline = time.monotonic() + 5
        while not self.endpoint.exists():
            if self.service.poll() is not None or time.monotonic() > deadline:
                self.fail("Review service failed to start")
            time.sleep(0.02)
        self.env = dict(os.environ, AGENT_REVIEW_SOCKET=str(self.endpoint))

    def stop_service(self):
        self.service.terminate()
        try:
            self.service.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self.service.kill()
            self.service.wait(timeout=2)
        self.service.stderr.close()

    def cli(self, *args):
        result = subprocess.run(
            [sys.executable, str(fixtures.RUNTIME / "agent-review"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_real_stdio_mcp_and_cli_share_one_conversation(self):
        async def scenario():
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=sys.executable,
                args=[str(fixtures.RUNTIME / "review_mcp.py")],
                env=self.env,
            )
            async with stdio_client(params) as (reader, writer):  # noqa: SIM117 -- named streams initialize the nested session
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    self.assertEqual(
                        {t.name for t in listing.tools},
                        {
                            "review_start",
                            "review_reply",
                            "review_recheck",
                            "review_status",
                            "review_events",
                            "review_cancel",
                            "review_extend",
                        },
                    )

                    async def tool(name, **kwargs):
                        result = await session.call_tool(name, kwargs)
                        self.assertFalse(result.isError, result)
                        return result.structuredContent or json.loads(
                            result.content[0].text
                        )

                    first = await tool(
                        "review_start",
                        request_id="start-mcp",
                        brief=str(self.fixture.brief),
                    )
                    ident = first["review_id"]
                    cursor = first["cursor"]
                    for _ in range(15):
                        state = await tool(
                            "review_events",
                            review_id=ident,
                            after=cursor,
                            wait_seconds=1,
                        )
                        cursor = state["cursor"]
                        if state["status"] in fixtures.review.TERMINAL | {
                            "waiting_reply"
                        }:
                            break
                    self.assertEqual(state["status"], "waiting_reply", state)
                    message = {
                        "answers": [
                            {
                                "question_id": "q1",
                                "answer": "Subject-wise",
                                "evidence": ["source/code.py"],
                            }
                        ],
                        "questions": [],
                        "include": [],
                    }
                    path = self.fixture.run / "artifacts/answer.json"
                    path.write_text(json.dumps(message))
                    self.cli(
                        "reply",
                        ident,
                        "--request-id",
                        "answer-cli",
                        "--reply-to",
                        state["question"]["message_id"],
                        "--message-file",
                        str(path),
                    )
                    for _ in range(15):
                        state = await tool(
                            "review_events",
                            review_id=ident,
                            after=state["cursor"],
                            wait_seconds=1,
                        )
                        if state["status"] in fixtures.review.TERMINAL:
                            break
                    self.assertEqual(state["status"], "success", state)
                    self.assertEqual(
                        self.cli("status", ident)["session_id"], state["session_id"]
                    )
                    self.assertEqual(state["verdict"], "approve")
                    duplicate = await tool(
                        "review_start",
                        request_id="start-mcp",
                        brief=str(self.fixture.brief),
                    )
                    self.assertEqual(duplicate["review_id"], ident)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
