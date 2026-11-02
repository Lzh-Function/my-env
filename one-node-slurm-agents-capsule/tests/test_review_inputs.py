"""Real MCP transport and directory confinement, without a provider/model."""

import asyncio
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "runtime/agentrun/review_inputs.py"


def pdf(text):
    """Build a one-page PDF with a correct cross-reference table."""
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    body, offsets = b"%PDF-1.4\n", []
    for number, value in enumerate(objects, 1):
        offsets.append(len(body))
        body += b"%d 0 obj\n%s\nendobj\n" % (number, value)
    xref = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    body += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    return body + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)


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
                        {"list_files", "read_file", "search_text", "view_image", "read_pdf_text",
                         "view_pdf_page"},
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
                    result = await call("view_image", path="figures/plot.png")
                    self.assertFalse(result.isError, result.content)
                    self.assertEqual(result.content[0].type, "image")
                    self.assertEqual(result.content[0].mimeType, "image/png")
                    for path in ("source/code.py", "../outside.txt", "source/link"):
                        result = await call("view_image", path=path)
                        self.assertTrue(result.isError, path)
                    result = await call("read_pdf_text", path="source/code.py")
                    self.assertTrue(result.isError)
                    if shutil.which("pdftoppm") and shutil.which("pdfinfo"):
                        result = await call("read_pdf_text", path="paper.pdf")
                        self.assertFalse(result.isError, result.content)
                        data = result.structuredContent or json.loads(result.content[0].text)
                        self.assertIn("Hello PDF", data["text"])
                        self.assertEqual((data["pages"], data["next_page"]), (1, None))
                        result = await call("view_pdf_page", path="paper.pdf")
                        self.assertFalse(result.isError, result.content)
                        self.assertEqual(result.content[0].mimeType, "image/png")
                        result = await call("view_pdf_page", path="paper.pdf", page=2)
                        self.assertTrue(result.isError)
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
            (root / "paper.pdf").write_bytes(pdf("Hello PDF"))
            (root / "figures").mkdir()
            (root / "figures/plot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(32))
            (root / "source/link").symlink_to(parent / "outside.txt")
            asyncio.run(scenario(root))
            self.assertEqual(
                (root / "source/code.py").read_text(), "value = 1\n# second line\n"
            )


if __name__ == "__main__":
    unittest.main()
