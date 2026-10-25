"""Real MCP transport and directory confinement, without a provider/model."""

import asyncio
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "runtime/agentrun/review_inputs.py"


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Requires mcp==1.26.0")
class InputReaderTests(unittest.TestCase):
    def test_real_stdio_reads_paginate_and_reject_escapes_and_write_tools(self):
        async def scenario(root):
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=sys.executable, args=[str(SCRIPT), str(root)]
            )
            async with stdio_client(params) as (reader, writer):  # noqa: SIM117 -- the session needs the initialized streams
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    self.assertEqual(
                        {t.name for t in listing.tools},
                        {"list_files", "read_file", "search_text"},
                    )
                    self.assertTrue(
                        all(t.annotations.readOnlyHint for t in listing.tools)
                    )

                    async def call(name, **kwargs):
                        return await session.call_tool(name, kwargs)

                    result = await call("read_file", path="source/code.py", max_lines=1)
                    self.assertFalse(result.isError)
                    data = result.structuredContent or json.loads(
                        result.content[0].text
                    )
                    self.assertEqual(data["content"], "1: value = 1")
                    self.assertEqual(data["next_line"], 2)
                    result = await call("search_text", text="second")
                    data = result.structuredContent or json.loads(
                        result.content[0].text
                    )
                    self.assertEqual(data["matches"][0]["line"], 2)
                    for path in (
                        "../outside.txt",
                        str(root.parent / "outside.txt"),
                        "source/link",
                    ):
                        result = await call("read_file", path=path)
                        self.assertTrue(result.isError, path)
                        self.assertNotIn("OUTSIDE_SECRET", str(result.content))
                    result = await call(
                        "write_file", path="source/code.py", content="changed"
                    )
                    self.assertTrue(result.isError)

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "input"
            (root / "source").mkdir(parents=True)
            (root / "source/code.py").write_text("value = 1\n# second line\n")
            (parent / "outside.txt").write_text("OUTSIDE_SECRET")
            (root / "source/link").symlink_to(parent / "outside.txt")
            asyncio.run(scenario(root))
            self.assertEqual(
                (root / "source/code.py").read_text(), "value = 1\n# second line\n"
            )


if __name__ == "__main__":
    unittest.main()
