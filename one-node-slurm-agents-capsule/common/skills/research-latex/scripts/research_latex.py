#!/usr/bin/env python3
"""Portable project initializer, LuaLaTeX builder and PDF QA helper.

Works with Python 3 stdlib, TeX Live, latexmk, Biber and Poppler.
Do not run on untrusted TeX sources: TeX macros and BibTeX processing
are code-like inputs even when unrestricted shell escape is disabled.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
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
    out_dir = project / "build"
    out_dir.mkdir(parents=True, exist_ok=True)
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
    if "/" in args.output or "\\" in args.output or not args.output.lower().endswith(".pdf"):
        print("--output must be a simple PDF filename, e.g. report.pdf", file=sys.stderr)
        return 2
    target = project / args.output
    shutil.copy2(out_dir / "main.pdf", target)
    print(f"PDF produced: {target}")
    code = validate_pdf(project, target, strict=args.strict)
    print("Visual inspection is NOT automated; run 'render' and inspect every page with an image-capable agent.")
    return code


def pdf_info(pdf: Path) -> tuple[int, str]:
    info = invoke(["pdfinfo", str(pdf)])
    if info.returncode != 0:
        raise RuntimeError("pdfinfo failed: " + info.stdout[-1200:])
    match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, flags=re.M)
    if not match:
        raise RuntimeError("Could not determine page count")
    return int(match.group(1)), info.stdout


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
            count = len(re.findall(pat, log_text, re.I))
            if count:
                warnings.append((label, count))
    else:
        print("WARNING: build/main.log not found; TeX warnings could not be analyzed")
    for label, count in warnings:
        print(f"WARNING: {label}: {count}")
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


def command_render(args: argparse.Namespace) -> int:
    project = project_path(args.project)
    pdf = project / args.pdf
    pages, _ = pdf_info(pdf)
    first = args.from_page
    last = pages if args.all else min(pages, args.to_page)
    if first > last or first < 1:
        print(f"Invalid page range: {first}..{last} (PDF has {pages} pages)", file=sys.stderr)
        return 2
    dest = project / args.output_dir
    dest.mkdir(parents=True, exist_ok=True)
    prefix = dest / "page"
    cmd = ["pdftoppm", "-f", str(first), "-l", str(last), "-r", str(args.dpi), "-png", str(pdf), str(prefix)]
    res = invoke(cmd)
    if res.returncode:
        print("Rendering failed:\n" + res.stdout[-2000:], file=sys.stderr)
        return res.returncode
    rendered = sorted(dest.glob("page-*.png"))
    print(f"Rendered {len(rendered)} page(s) into {dest} (requested {first}–{last} / {pages})")
    if last < pages:
        print(f"WARNING: not all {pages} pages rendered; use --all for full visual QA.")
    print("An image-capable agent or a human must inspect each generated image for clipping, layout, missing glyphs and bad floats.")
    return 0


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
    r.set_defaults(func=command_render)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError, RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
