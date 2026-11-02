#!/usr/bin/env python3
"""Read-only MCP tools scoped to one immutable review input directory."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from mcp.server.fastmcp import FastMCP, Image
from mcp.types import ToolAnnotations
from review_snapshot import MAX_FILES, safe_file
from review_snapshot import read_file as read_snapshot_file

MAX_OUTPUT = 128 * 1024
# Image inputs larger than this are rejected by the model APIs anyway.
MAX_IMAGE = 20 * 1024 * 1024
# Poppler converts one page at a time; a page that takes longer is reported instead of waited for.
PDF_TIMEOUT = 60
PDF_DPI = 110
IMAGE_FORMATS = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpeg", b"GIF87a": "gif", b"GIF89a": "gif"}
READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, openWorldHint=False
)


def server(directory):
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Review input root is not a directory")
    mcp = FastMCP("capsule-input", log_level="WARNING")

    def paths(prefix):
        if Path(prefix).is_absolute() or ".." in Path(prefix).parts:
            raise ValueError("Use paths relative to the review input directory")
        base = safe_file(root / prefix, (root,))
        result = []
        for path in sorted(base.rglob("*") if base.is_dir() else [base]):
            if path.is_symlink():
                continue
            safe_file(path, (root,))
            if path.is_file():
                result.append(path)
                if len(result) > MAX_FILES + 100:
                    raise ValueError("Too many review input files")
        return result

    @mcp.tool(annotations=READ_ONLY)
    def list_files(prefix: str = "", offset: int = 0, limit: int = 200) -> dict:
        """List captured files only. Paths are relative to this review's input root."""
        if offset < 0 or not 1 <= limit <= 1000:
            raise ValueError(
                "offset must be nonnegative; limit must be between 1 and 1000"
            )
        files = paths(prefix)
        return {
            "files": [
                {"path": p.relative_to(root).as_posix(), "size": p.stat().st_size}
                for p in files[offset : offset + limit]
            ],
            "total": len(files),
            "next_offset": offset + limit if offset + limit < len(files) else None,
        }

    @mcp.tool(annotations=READ_ONLY)
    def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> dict:
        """Read UTF-8 evidence, manifest.json or diff.patch with line numbers; paginate large files."""
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError(
                "Use a relative snapshot path, not an original workspace path"
            )
        if start_line < 1 or not 1 <= max_lines <= 2000:
            raise ValueError(
                "start_line must be positive; max_lines must be between 1 and 2000"
            )
        lines = read_snapshot_file(root / path, (root,)).decode("utf-8").splitlines()
        selected, size = [], 0
        for number, line in enumerate(
            lines[start_line - 1 : start_line - 1 + max_lines], start_line
        ):
            formatted = f"{number}: {line}"
            if size + len(formatted.encode()) > MAX_OUTPUT:
                if not selected:
                    raise ValueError(
                        "One line exceeds the output limit; provide a smaller text artifact"
                    )
                break
            selected.append(formatted)
            size += len(formatted.encode())
        next_line = start_line + len(selected)
        return {
            "path": path,
            "content": "\n".join(selected),
            "total_lines": len(lines),
            "next_line": next_line if next_line <= len(lines) else None,
        }

    @mcp.tool(annotations=READ_ONLY)
    def view_image(path: str) -> Image:
        """View a captured PNG, JPEG, GIF or WebP image (figures, plots) listed in binary_files."""
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Use a relative snapshot path, not an original workspace path")
        content = read_snapshot_file(root / path, (root,))
        if len(content) > MAX_IMAGE:
            raise ValueError("Image is larger than 20 MiB; ask for a smaller export")
        kind = next((name for magic, name in IMAGE_FORMATS.items() if content.startswith(magic)), None)
        if kind is None and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
            kind = "webp"
        if kind is None:
            raise ValueError("Not a PNG, JPEG, GIF or WebP image; this reader cannot display it")
        return Image(data=content, format=kind)

    def pdf(path, page, tool, *args):
        """Run a Poppler tool on a private copy of one captured PDF page."""
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Use a relative snapshot path, not an original workspace path")
        if page < 1:
            raise ValueError("page must be positive")
        if any(shutil.which(name) is None for name in (tool, "pdfinfo")):
            raise ValueError("poppler-utils is not installed; this PDF cannot be converted")
        content = read_snapshot_file(root / path, (root,))
        if not content.startswith(b"%PDF-"):
            raise ValueError("Not a PDF file")
        with tempfile.TemporaryDirectory() as scratch:
            source = Path(scratch) / "input.pdf"
            source.write_bytes(content)
            try:
                info = subprocess.run(["pdfinfo", str(source)], capture_output=True, text=True,
                                      timeout=PDF_TIMEOUT, check=True).stdout
                pages = int(next(line.split()[-1] for line in info.splitlines() if line.startswith("Pages:")))
            except (subprocess.SubprocessError, OSError, StopIteration, ValueError) as error:
                raise ValueError("Cannot read the PDF page count") from error
            if page > pages:
                raise ValueError(f"page must be at most {pages}")
            try:
                result = subprocess.run([tool, "-f", str(page), "-l", str(page), *args, str(source),
                                         str(Path(scratch) / "out")],
                                        capture_output=True, timeout=PDF_TIMEOUT, check=True)
            except subprocess.TimeoutExpired as error:
                raise ValueError("PDF conversion timed out for this page") from error
            except (subprocess.SubprocessError, OSError) as error:
                raise ValueError("PDF conversion failed for this page") from error
            outputs = sorted(Path(scratch).glob("out*"))
            return pages, (outputs[0].read_bytes() if outputs else result.stdout)

    @mcp.tool(annotations=READ_ONLY)
    def view_pdf_page(path: str, page: int = 1) -> Image:
        """View one page of a captured PDF from binary_files as a PNG image (figures, layout, tables)."""
        _, image = pdf(path, page, "pdftoppm", "-png", "-r", str(PDF_DPI), "-singlefile")
        if len(image) > MAX_IMAGE:
            raise ValueError("Rendered page is larger than 20 MiB")
        return Image(data=image, format="png")

    @mcp.tool(annotations=READ_ONLY)
    def read_pdf_text(path: str, page: int = 1) -> dict:
        """Read the text of one page of a captured PDF from binary_files, keeping its layout."""
        pages, text = pdf(path, page, "pdftotext", "-layout", "-enc", "UTF-8")
        text = text.decode("utf-8", errors="replace")
        truncated = len(text.encode()) > MAX_OUTPUT
        if truncated:
            text = text.encode()[:MAX_OUTPUT].decode("utf-8", errors="ignore")
        return {"path": path, "page": page, "pages": pages, "text": text, "truncated": truncated,
                "next_page": page + 1 if page < pages else None}

    @mcp.tool(annotations=READ_ONLY)
    def search_text(text: str, prefix: str = "", max_matches: int = 100) -> dict:
        """Find a literal UTF-8 string in captured text; no regex, shell or repository code execution."""
        if not text or not 1 <= max_matches <= 1000:
            raise ValueError(
                "text must be nonempty; max_matches must be between 1 and 1000"
            )
        matches, size = [], 0
        for path in paths(prefix):
            try:
                content = read_snapshot_file(path, (root,)).decode("utf-8")
            except UnicodeError:
                continue
            for number, line in enumerate(content.splitlines(), 1):
                if text in line:
                    match = {
                        "path": path.relative_to(root).as_posix(),
                        "line": number,
                        "text": line[:2000],
                    }
                    size += len(json.dumps(match).encode())
                    if size > MAX_OUTPUT or len(matches) == max_matches:
                        return {"matches": matches, "truncated": True}
                    matches.append(match)
        return {"matches": matches, "truncated": False}

    return mcp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.directory.resolve(strict=True)
    service = server(root)
    if args.check:
        json.loads(read_snapshot_file(root / "manifest.json", (root,)))
        read_snapshot_file(root / "diff.patch", (root,))
        print("CAPSULE_REVIEW_INPUTS_READY")
    else:
        service.run(transport="stdio")


if __name__ == "__main__":
    main()
