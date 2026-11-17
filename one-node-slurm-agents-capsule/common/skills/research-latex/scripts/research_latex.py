#!/usr/bin/env python3
"""Portable project initializer, LuaLaTeX builder, PDF QA and number-provenance helper.

Works with Python 3 stdlib, TeX Live, latexmk, Biber and Poppler.
Do not run on untrusted TeX sources: TeX macros and BibTeX processing
are code-like inputs even when unrestricted shell escape is disabled.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = {"academic": "academic", "technical": "technical", "monograph": "monograph"}
REQUIRED_EXEC = ("lualatex", "latexmk", "biber", "kpsewhich", "pdfinfo", "pdftotext", "pdftoppm")
REQUIRED_TEX = (
    "ltjsarticle.cls", "ltjsbook.cls", "luatexja-fontspec.sty", "fontspec.sty",
    "biblatex.sty", "booktabs.sty", "siunitx.sty", "tcolorbox.sty",
    "cleveref.sty", "hyperref.sty", "csquotes.sty",
    "caption.sty", "listings.sty", "fancyhdr.sty", "multirow.sty", "enumitem.sty",
    "lmroman10-regular.otf", "HaranoAjiMincho-Regular.otf", "HaranoAjiGothic-Medium.otf",
)


def invoke(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=cwd, text=True, errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)


def project_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def command_doctor(args: argparse.Namespace) -> int:
    print("Checking research-latex prerequisites (no installation performed)\n")
    missing = []
    for name in REQUIRED_EXEC:
        path = shutil.which(name)
        print(f"{'OK' if path else 'MISSING':7s} executable: {name:14s} {path or ''}")
        if path is None:
            missing.append(name)
    kpsewhich = shutil.which("kpsewhich")
    if kpsewhich:
        for name in REQUIRED_TEX:
            result = invoke([kpsewhich, name])
            found = result.returncode == 0 and result.stdout.strip()
            print(f"{'OK' if found else 'MISSING':7s} TeX package: {name}")
            if not found:
                missing.append(name)
    print("\n" + ("Missing prerequisites: " + ", ".join(missing) if missing else "All required command/package checks passed."))
    print("See INSTALL.md for OS package instructions; font rendering also requires a build test.")
    return int(bool(missing))


def copy_file(source: Path, target: Path, force: bool) -> None:
    if target.exists() and not force:
        raise FileExistsError(f"Existing file (use --force only if overwriting is intended): {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def command_init(args: argparse.Namespace) -> int:
    dest = project_path(args.output)
    files = [
        (ROOT / "assets/templates" / args.template / "main.tex", dest / "main.tex"),
        (ROOT / "assets/common/preamble.tex", dest / "preamble.tex"),
        (ROOT / "assets/examples/references.bib", dest / "references.bib"),
        (ROOT / "assets/examples/example-curve.pdf", dest / "figures/example-curve.pdf"),
        (ROOT / "assets/examples/example-metrics.csv", dest / "data/example-metrics.csv"),
        (ROOT / "scripts/plot_example.py", dest / "scripts/plot_example.py"),
        (ROOT / "assets/common/verify_claims.py", dest / "scripts/verify_claims.py"),
    ]
    conflicts = [str(d) for _, d in files if d.exists()]
    if conflicts and not args.force:
        print("Refusing to overwrite existing files:\n  " + "\n  ".join(conflicts), file=sys.stderr)
        return 2
    dest.mkdir(parents=True, exist_ok=True)
    for source, target in files:
        copy_file(source, target, args.force)
    print(f"Initialized {args.template} project at: {dest}")
    print(f"Next: uv run --no-project python {ROOT / 'scripts/research_latex.py'} build --project {dest}")
    print("Replace synthetic/example content, figures and references before distributing a research report.")
    return 0


def check_project(path: Path) -> None:
    for f in ("main.tex", "preamble.tex", "references.bib"):
        if not (path / f).is_file():
            raise FileNotFoundError(f"Missing {f} in project: {path}")


def command_build(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    check_project(project)
    if "/" in args.output or "\\" in args.output or not args.output.lower().endswith(".pdf"):
        print("--output must be a simple PDF filename, e.g. report.pdf", file=sys.stderr)
        return 2
    out_dir = project / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Two latexmk runs sharing build/ corrupt each other's intermediates
    # (e.g. Biber reads a half-written main.bcf), so refuse a second build.
    with (out_dir / ".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("ERROR: another build is running in this project (build/.lock).\n"
                  "Wait for it to finish; the lock is released when that process exits.", file=sys.stderr)
            return 1
        return locked_build(project, out_dir, args)


def locked_build(project: Path, out_dir: Path, args: argparse.Namespace) -> int:
    cmd = [
        "latexmk", "-lualatex", "-interaction=nonstopmode", "-halt-on-error",
        "-file-line-error", "-synctex=1", "-outdir=build", "main.tex",
    ]
    print(f"Building: {project / 'main.tex'}")
    result = invoke(cmd, cwd=project)
    (out_dir / "build-command.log").write_text(result.stdout, encoding="utf-8")
    if result.returncode != 0 or not (out_dir / "main.pdf").is_file():
        print("BUILD FAILED. Last 45 lines of build/build-command.log:", file=sys.stderr)
        print("\n".join(result.stdout.splitlines()[-45:]), file=sys.stderr)
        return 1
    target = project / args.output
    shutil.copy2(out_dir / "main.pdf", target)
    print(f"PDF produced: {target}")
    code = validate_pdf(project, target, strict=args.strict)
    if not args.no_verify:
        print()
        code = max(code, verify_project(project, run_slow=False, list_sentences=False))
    print("Visual inspection is NOT automated; run 'render --changed' (or '--all' before delivery) and inspect the pages.")
    return code


def pdf_info(pdf: Path) -> tuple[int, str]:
    info = invoke(["pdfinfo", str(pdf)])
    if info.returncode != 0:
        raise RuntimeError("pdfinfo failed: " + info.stdout[-1200:])
    match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, flags=re.MULTILINE)
    if not match:
        raise RuntimeError("Could not determine page count")
    return int(match.group(1)), info.stdout


WARNING_DETAIL_LIMIT = 5
LOG_FILE_OPEN = re.compile(r"\(((?:[A-Za-z]:)?[^\s()]+\.(?:tex|sty|cls|cfg|def|clo|ldf|fd|aux|toc|lof|lot|bbl|out))")
LOG_LINES = re.compile(r"(?:at lines? (\d+(?:--\d+)?)|on input line (\d+))")


def log_locations(project: Path, log_text: str, pattern: str) -> list[str]:
    """Describe each match of pattern with the project .tex file TeX had open.

    TeX opens a file with "(path" and closes it with ")"; replaying that
    parenthesis stack up to a warning tells which file the warning belongs to.
    Unbalanced parentheses inside messages can confuse the stack, so the file
    is a best-effort hint, the line numbers come verbatim from the message.
    """
    matches = list(re.finditer(pattern, log_text, re.IGNORECASE))
    stack: list[str | None] = []
    position = 0
    found = []
    for match in matches:
        segment = log_text[position:match.start()]
        index = 0
        while index < len(segment):
            char = segment[index]
            if char == "(":
                opened = LOG_FILE_OPEN.match(segment, index)
                stack.append(opened.group(1) if opened else None)
                index = opened.end() if opened else index + 1
                continue
            if char == ")" and stack:
                stack.pop()
            index += 1
        position = match.start()
        source = next((name for name in reversed(stack) if name and name.endswith(".tex")
                       and (project / name).resolve().is_relative_to(project)), None)
        line_end = log_text.find("\n", match.start())
        message = log_text[match.start():line_end if line_end >= 0 else len(log_text)].strip()
        lines = LOG_LINES.search(message)
        where = Path(source).as_posix().removeprefix("./") if source else "?"
        if lines:
            where += f", {'lines ' + lines.group(1) if lines.group(1) else 'input line ' + lines.group(2)}"
        found.append(f"{where}: {message[:160]}")
    return found


def validate_pdf(project: Path, pdf: Path, strict: bool = False) -> int:
    if not pdf.is_file() or pdf.stat().st_size == 0:
        print(f"ERROR: PDF missing or empty: {pdf}", file=sys.stderr)
        return 1
    pages, info = pdf_info(pdf)
    print(f"PDF: {pdf.name}, {pages} page(s), {pdf.stat().st_size:,} bytes")
    if pages < 1:
        return 1
    text_extraction = invoke(["pdftotext", "-layout", str(pdf), "-"])
    if text_extraction.returncode != 0 or len(text_extraction.stdout.strip()) < 60:
        print("ERROR: PDF text extraction failed or yielded unusually little text", file=sys.stderr)
        return 1
    warnings = []
    log = project / "build/main.log"
    if log.exists():
        log_text = log.read_text(encoding="utf-8", errors="replace")
        patterns = {
            "undefined-reference": r"LaTeX Warning:.*(?:Reference|Citation).*undefined|There were undefined references|Please \(re\)run Biber",
            "missing-character": r"Missing character:",
            "overfull-box": r"Overfull \\[hv]box",
            "underfull-box": r"Underfull \\[hv]box",
        }
        for label, pat in patterns.items():
            hits = log_locations(project, log_text, pat)
            if hits:
                warnings.append((label, len(hits)))
                print(f"WARNING: {label}: {len(hits)}")
                for where in hits[:WARNING_DETAIL_LIMIT]:
                    print("  " + where)
                if len(hits) > WARNING_DETAIL_LIMIT:
                    print(f"  ... and {len(hits) - WARNING_DETAIL_LIMIT} more (see build/main.log)")
    else:
        print("WARNING: build/main.log not found; TeX warnings could not be analyzed")
    serious = {"undefined-reference", "missing-character"}
    failures = [x for x in warnings if x[0] in serious or strict]
    print(f"Text extraction: OK ({len(text_extraction.stdout):,} characters)")
    if failures:
        print("VALIDATION FAILED due to warnings: " + ", ".join(n for n, _ in failures))
        return 1
    print("Structural validation: OK. Manual visual inspection still required.")
    return 0


def command_validate(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    return validate_pdf(project, project / args.pdf, strict=args.strict)


PAGE_PNG = re.compile(r"page-(\d+)\.png")


def rendered_pages(directory: Path) -> dict[int, Path]:
    pages = {}
    for path in directory.glob("page-*.png"):
        match = PAGE_PNG.fullmatch(path.name)
        if match:
            pages[int(match.group(1))] = path
    return pages


def page_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_changed(project: Path, pdf: Path, pages: int, dest: Path, dpi: int) -> int:
    """Rasterize every page, keep only pages that differ from the last render, plus their neighbours."""
    state_file = dest / "page-hashes.json"
    previous = {}
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state.get("dpi") == dpi and state.get("pdf") == pdf.name:
            previous = {int(page): digest for page, digest in state["pages"].items()}
    scratch = project / "build/.render-scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    res = invoke(["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(scratch / "page")])
    if res.returncode:
        print("Rendering failed:\n" + res.stdout[-2000:], file=sys.stderr)
        return res.returncode
    fresh = rendered_pages(scratch)
    if sorted(fresh) != list(range(1, pages + 1)):
        raise RuntimeError(f"pdftoppm produced {len(fresh)} page image(s) for a {pages}-page PDF")
    digests = {page: page_digest(path) for page, path in fresh.items()}
    changed = sorted(page for page, digest in digests.items() if previous.get(page) != digest)
    selected = sorted({near for page in changed for near in (page - 1, page, page + 1) if 1 <= near <= pages})
    dest.mkdir(parents=True, exist_ok=True)
    for old in rendered_pages(dest).values():
        old.unlink()
    for page in selected:
        fresh[page].replace(dest / fresh[page].name)
    shutil.rmtree(scratch)
    state_file.write_text(json.dumps({"pdf": pdf.name, "dpi": dpi, "pages": digests}, indent=1) + "\n", encoding="utf-8")
    if not previous:
        print(f"No earlier render at {dpi} dpi to compare with; rendered all {pages} page(s) into {dest}")
    elif not changed:
        print(f"No page changed since the last render ({pages} pages); nothing to inspect.")
    else:
        print(f"Changed page(s): {', '.join(map(str, changed))} of {pages}")
        print(f"Rendered {len(selected)} page(s) (changed pages and their neighbours) into {dest}")
    print("Inspect each generated image. Before delivery, run 'render --all' once and inspect every page.")
    return 0


def command_render(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    pdf = project / args.pdf
    pages, _ = pdf_info(pdf)
    if args.changed:
        return render_changed(project, pdf, pages, project / args.output_dir, args.dpi)
    first = args.from_page
    last = pages if args.all else min(pages, args.to_page)
    if first > last or first < 1:
        print(f"Invalid page range: {first}..{last} (PDF has {pages} pages)", file=sys.stderr)
        return 2
    dest = project / args.output_dir
    dest.mkdir(parents=True, exist_ok=True)
    # Drop images from earlier renders so the directory holds only this PDF's pages.
    for old in rendered_pages(dest).values():
        old.unlink()
    prefix = dest / "page"
    cmd = ["pdftoppm", "-f", str(first), "-l", str(last), "-r", str(args.dpi), "-png", str(pdf), str(prefix)]
    res = invoke(cmd)
    if res.returncode:
        print("Rendering failed:\n" + res.stdout[-2000:], file=sys.stderr)
        return res.returncode
    # Record what was rendered so a later 'render --changed' compares against it.
    state_file = dest / "page-hashes.json"
    known = {}
    if state_file.is_file():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        if state.get("dpi") == args.dpi and state.get("pdf") == pdf.name:
            known = {int(page): digest for page, digest in state["pages"].items() if int(page) <= pages}
    known.update({page: page_digest(path) for page, path in rendered_pages(dest).items()})
    state_file.write_text(json.dumps({"pdf": pdf.name, "dpi": args.dpi, "pages": known}, indent=1) + "\n", encoding="utf-8")
    rendered = sorted(dest.glob("page-*.png"))
    print(f"Rendered {len(rendered)} page(s) into {dest} (requested {first}–{last} / {pages})")
    if last < pages:
        print(f"WARNING: not all {pages} pages rendered; use --all for full visual QA.")
    print("An image-capable agent or a human must inspect each generated image for clipping, layout, missing glyphs and bad floats.")
    return 0


# ---------------------------------------------------------------------------
# Number provenance: crosscheck (summary vs body) and verify (claims + scan)
# ---------------------------------------------------------------------------

COMMENT = re.compile(r"(?<!\\)%.*")
NUMBER = re.compile(r"(?<![A-Za-z\d.])\d+(?:(?:,|\{,\})\d{3})*(?:\.\d+)?(?!\d)")
# Arguments that hold keys, paths or layout values rather than claims.
NON_CLAIM = re.compile(
    r"\\(?:label|ref|cref|Cref|eqref|autoref|pageref|nameref|cite\w*|\w*cite|includegraphics|input|include"
    r"|url|href|begin|end|vspace|hspace|fontsize|setlength|addtolength)\*?(?:\[[^\]]*\])*(?:\{[^{}]*\})*"
    r"|\d*\.?\d+\s*(?:pt|mm|cm|em|ex|in|bp)\b|\d*\.?\d+\\(?:text|line|column|paper)width|\\\\\[[^\]]*\]"
    r"|_(?:\{[^{}]*\}|\d+)")  # math subscripts are indices, not quantities
SOURCE_MARK = re.compile(r"\\(?:cite\w*|\w*cite|ref|cref|Cref|eqref|autoref|pageref|label)\b")
CITE_WITH_LOCATION = re.compile(r"\\\w*cite\w*\*?\[[^\]]+\]")
CITE = re.compile(r"\\\w*cite\w*\b")
SKIPPED_ENVIRONMENTS = {
    "table", "table*", "figure", "figure*", "tabular", "tabular*", "tabularx", "longtable", "equation",
    "equation*", "align", "align*", "gather", "gather*", "lstlisting", "verbatim", "thebibliography",
    "tikzpicture", "titlepage",
}
SUMMARY_BEGIN = "% research-latex: summary-begin"
SUMMARY_END = "% research-latex: summary-end"


def body_files(project: Path) -> list[Path]:
    """Every project .tex file latexmk actually read, in reading order (from build/main.fls)."""
    fls = project / "build/main.fls"
    if not fls.is_file():
        raise FileNotFoundError(f"{fls} not found; run 'build' first")
    seen, out = set(), []
    for line in fls.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("INPUT ") and line.endswith(".tex"):
            path = (project / line[6:]).resolve()
            if path.is_file() and path.is_relative_to(project) and not path.is_relative_to(project / "build") \
                    and path not in seen:
                seen.add(path)
                out.append(path)
    if not out:
        raise RuntimeError(f"{fls} lists no project .tex files")
    return out


def tex_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def numbers_in(line: str) -> list[str]:
    text = NON_CLAIM.sub(" ", COMMENT.sub("", line))
    return [match.group(0).replace("{,}", "").replace(",", "") for match in NUMBER.finditer(text)]


def relative(project: Path, path: Path) -> str:
    return path.relative_to(project).as_posix()


def parse_range(project: Path, spec: str) -> tuple[Path, int, int]:
    """FILE or FILE:A-B, relative to the project; lines are 1-based and inclusive."""
    name, _, span = spec.partition(":")
    path = (project / name).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"region file not found: {spec}")
    lines = tex_lines(path)
    if not span:
        return path, 1, len(lines)
    match = re.fullmatch(r"(\d+)-(\d+)", span)
    if not match or not 1 <= int(match.group(1)) <= int(match.group(2)) <= len(lines):
        raise ValueError(f"invalid line range (file has {len(lines)} lines): {spec}")
    return path, int(match.group(1)), int(match.group(2))


def find_summary(project: Path, files: list[Path]) -> tuple[Path, int, int] | None:
    """The abstract environment, else the summary-begin/end markers; never a guess."""
    for opening, closing in ((r"\begin{abstract}", r"\end{abstract}"), (SUMMARY_BEGIN, SUMMARY_END)):
        for path in files:
            lines = tex_lines(path)
            starts = [i for i, line in enumerate(lines, 1) if line.strip().startswith(opening)]
            if not starts:
                continue
            ends = [i for i, line in enumerate(lines, 1) if line.strip().startswith(closing) and i > starts[0]]
            if not ends:
                raise ValueError(f"{relative(project, path)}:{starts[0]}: '{opening}' has no matching '{closing}'")
            return path, starts[0], ends[0]
    return None


def rounding_sources(value: str, body: dict[str, list[str]]) -> list[str]:
    """Body numbers that print as value once rounded (0.9662 -> 0.966)."""
    decimals = len(value.partition(".")[2])
    if decimals == 0 and Decimal(value) < 10:
        return []
    quantum = Decimal(1).scaleb(-decimals)
    target = Decimal(value)
    return [f"{candidate} at {where[0]}" for candidate, where in body.items()
            if len(candidate.partition(".")[2]) > decimals
            and Decimal(candidate).quantize(quantum, rounding=ROUND_HALF_UP) == target][:3]


def command_crosscheck(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    files = body_files(project)
    if args.summary_range:
        regions = [parse_range(project, args.summary_range)]
    else:
        summary = find_summary(project, files)
        if summary is None:
            print("ERROR: cannot tell where the summary is. Use \\begin{abstract}, wrap it in the lines\n"
                  f"  {SUMMARY_BEGIN}\n  {SUMMARY_END}\n"
                  "or pass --summary-range FILE:A-B.", file=sys.stderr)
            return 2
        regions = [summary]
    regions += [parse_range(project, spec) for spec in args.region]
    found = [(path, number, value) for path in files for number, line in enumerate(tex_lines(path), 1)
             for value in numbers_in(line)]
    status = 0
    for path, start, end in regions:
        # Each region is checked against everything outside itself, other regions included.
        body: dict[str, list[str]] = {}
        for other, number, value in found:
            if other != path or not start <= number <= end:
                body.setdefault(value, []).append(f"{relative(project, other)}:{number}")
        lines = tex_lines(path)
        missing, total = [], 0
        for number in range(start, end + 1):
            for value in numbers_in(lines[number - 1]):
                total += 1
                if value not in body:
                    missing.append((number, value))
        print(f"Region {relative(project, path)}:{start}-{end}: {total} number(s), {len(missing)} not found elsewhere")
        for number, value in missing:
            hint = rounding_sources(value, body)
            print(f"  {relative(project, path)}:{number}: {value}" + (f"  (rounds from {'; '.join(hint)})" if hint else ""))
        status = status or int(bool(missing))
    if status:
        print("Each listed number must be traced: a stale copy of a corrected body value, a rounding of a body\n"
              "value (check the rounding is intended), or a value that legitimately appears only here.")
    return 0


def scan_sentences(project: Path, files: list[Path]) -> tuple[list[str], list[str]]:
    """Prose sentences with numbers and no source mark, and with a citation that names no location."""
    unsourced, unlocated = [], []

    def finish(sentence: str, line: int, path: Path) -> None:
        text = " ".join(sentence.split())
        if not numbers_in(text):
            return
        where = f"{relative(project, path)}:{line}: {text[:140]}"
        if not SOURCE_MARK.search(text):
            unsourced.append(where)
        elif CITE.search(text) and not CITE_WITH_LOCATION.search(text) and not re.search(r"\\\w*ref\b", text):
            unlocated.append(where)

    for path in files:
        lines = tex_lines(path)
        joined = "\n".join(lines)
        if re.search(r"^\s*\\(?:usepackage|RequirePackage)\b", joined, re.MULTILINE) and r"\begin{document}" not in joined:
            continue  # a preamble file
        in_document = r"\documentclass" not in joined
        depth = 0
        buffer, buffer_line = "", 0
        for number, raw in enumerate(lines, 1):
            line = COMMENT.sub("", raw)
            if not in_document:
                in_document = r"\begin{document}" in line
                continue
            for kind, name in re.findall(r"\\(begin|end)\{([^}]*)\}", line):
                if name in SKIPPED_ENVIRONMENTS:
                    depth += 1 if kind == "begin" else -1
            if depth > 0 or re.search(r"\\end\{(?:" + "|".join(map(re.escape, SKIPPED_ENVIRONMENTS)) + r")\}", line):
                if buffer.strip():
                    finish(buffer, buffer_line, path)
                buffer = ""
                continue
            if not line.strip() or re.match(r"\s*\\(?:part|chapter|section|subsection|subsubsection|paragraph)\b", line):
                if buffer.strip():
                    finish(buffer, buffer_line, path)
                buffer = ""
                continue
            if re.match(r"\s*\\item\b", line) and buffer.strip():
                finish(buffer, buffer_line, path)
                buffer = ""
            pieces = re.split(r"(?<=[。．！？])|(?<=[.!?])\s+(?=\S)", line)
            for index, piece in enumerate(pieces):
                if not buffer.strip():
                    buffer_line = number
                buffer += piece + ("" if index < len(pieces) - 1 else " ")
                if index < len(pieces) - 1:
                    finish(buffer, buffer_line, path)
                    buffer = ""
        if buffer.strip():
            finish(buffer, buffer_line, path)
    return unsourced, unlocated


def verify_project(project: Path, run_slow: bool, list_sentences: bool) -> int:
    files = body_files(project)
    status = 0
    script = project / "scripts/verify_claims.py"
    if script.is_file():
        runner = ["uv", "run", "--quiet", "--script"] if shutil.which("uv") else [sys.executable]
        print(f"Running {relative(project, script)}{' --all' if run_slow else ''}")
        result = invoke([*runner, str(script), "--project", str(project), *(["--all"] if run_slow else [])], cwd=project)
        print(result.stdout.rstrip())
        if result.returncode:
            print("VERIFY FAILED: a recomputed number no longer matches the text (see above).")
            status = 1
    else:
        print("No scripts/verify_claims.py: numbers recomputable from your data (type A) are not checked.")
    unsourced, unlocated = scan_sentences(project, files)
    print(f"Source scan: {len(unsourced)} sentence(s) with numbers but no \\cite/\\ref/\\label; "
          f"{len(unlocated)} citing without a location (\\cite[Table 3]{{key}}).")
    if list_sentences:
        for title, rows in (("No source mark", unsourced), ("Citation without location", unlocated)):
            if rows:
                print(f"{title}:")
                print("\n".join("  " + row for row in rows))
        print("Not every listed sentence needs a source (in-text arithmetic, counts like 'three types'),\n"
              "but every number must be type A (in verify_claims.py), B (cited with location) or C (derived here).")
    elif unsourced or unlocated:
        print("Run 'verify' to list them.")
    return status


def command_verify(args: argparse.Namespace) -> int:
    return verify_project(project_path(args.project), run_slow=args.all, list_sentences=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reusable scientific LuaLaTeX report skill utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="Verify required programs and TeX packages")
    d.set_defaults(func=command_doctor)
    i = sub.add_parser("init", help="Create a complete self-contained report project")
    i.add_argument("--template", choices=list(TEMPLATES), default="technical")
    i.add_argument("--output", required=True, help="Destination project directory")
    i.add_argument("--force", action="store_true", help="Overwrite generated template files only")
    i.set_defaults(func=command_init)
    b = sub.add_parser("build", help="Compile and run structural PDF validation")
    b.add_argument("--project", default=".")
    b.add_argument("--output", default="report.pdf")
    b.add_argument("--strict", action="store_true", help="Fail on any logged box warning as well")
    b.add_argument("--no-verify", action="store_true", help="Skip scripts/verify_claims.py and the source scan")
    b.set_defaults(func=command_build)
    v = sub.add_parser("validate", help="Run structural PDF checks")
    v.add_argument("--project", default=".")
    v.add_argument("--pdf", default="report.pdf")
    v.add_argument("--strict", action="store_true")
    v.set_defaults(func=command_validate)
    r = sub.add_parser("render", help="Render PDF pages to PNG for visual QA")
    r.add_argument("--project", default=".")
    r.add_argument("--pdf", default="report.pdf")
    r.add_argument("--output-dir", default="build/rendered")
    r.add_argument("--dpi", type=int, default=130)
    r.add_argument("--from-page", type=int, default=1)
    r.add_argument("--to-page", type=int, default=30)
    r.add_argument("--all", action="store_true", help="Render through the final page")
    r.add_argument("--changed", action="store_true",
                   help="Render only pages that differ from the last render, plus their neighbours")
    r.set_defaults(func=command_render)
    c = sub.add_parser("crosscheck", help="List summary numbers that appear nowhere else in the document")
    c.add_argument("--project", default=".")
    c.add_argument("--summary-range", metavar="FILE:A-B", help="Summary lines when there is no abstract or marker")
    c.add_argument("--region", action="append", default=[], metavar="FILE[:A-B]",
                   help="Another region that restates body numbers (conclusions, limitations); repeatable")
    c.set_defaults(func=command_crosscheck)
    f = sub.add_parser("verify", help="Run scripts/verify_claims.py and list numbers without a stated source")
    f.add_argument("--project", default=".")
    f.add_argument("--all", action="store_true", help="Also run checks registered with slow=True")
    f.set_defaults(func=command_verify)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
