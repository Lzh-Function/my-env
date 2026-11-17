"""research-latex: number provenance checks, build locking, warning locations and changed-page rendering.

TeX itself is not needed: the tests stand in build/main.fls, build/main.log and
Poppler with small fakes, which is all these features read.
"""

import fcntl
import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "common/skills/research-latex"
CLI = SKILL / "scripts/research_latex.py"

spec = importlib.util.spec_from_file_location("research_latex", CLI)
research_latex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(research_latex)

FAKE_PDFINFO = """#!/usr/bin/env python3
import sys
print("Pages: %d" % len(open(sys.argv[1]).read().split("\\n---\\n")))
"""
# Writes one "image" per page whose bytes are that page's text, like pdftoppm's page-N.png.
FAKE_PDFTOPPM = """#!/usr/bin/env python3
import sys
args = sys.argv[1:]
first = int(args[args.index("-f") + 1]) if "-f" in args else 1
pdf, prefix = args[-2], args[-1]
pages = open(pdf).read().split("\\n---\\n")
last = int(args[args.index("-l") + 1]) if "-l" in args else len(pages)
for number in range(first, last + 1):
    open("%s-%d.png" % (prefix, number), "w").write(pages[number - 1])
"""


class ResearchLatexTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="research latex ")
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / "report"
        (self.project / "build").mkdir(parents=True)
        (self.project / "sections").mkdir()
        for name in ("preamble.tex", "references.bib"):
            (self.project / name).write_text("% stub\n")

    def write(self, name, text):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")

    def fls(self, *names):
        lines = ["PWD " + str(self.project), "INPUT /usr/share/texlive/texmf-dist/tex/latex/base/size10.clo"]
        lines += [f"INPUT ./{name}" for name in names] + ["INPUT ./build/main.aux"]
        (self.project / "build/main.fls").write_text("\n".join(lines) + "\n")

    def cli(self, *args, expected=0, env=None):
        result = subprocess.run([sys.executable, str(CLI), *args, "--project", str(self.project)],
                                capture_output=True, text=True, timeout=120, check=False,
                                env=dict(os.environ, **(env or {})))
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def test_crosscheck_lists_summary_numbers_missing_from_the_body(self):
        self.write("main.tex", r"""
            \documentclass{ltjsarticle}
            \input{preamble.tex}
            \begin{document}
            \begin{abstract}
            チオール系は24.32\%を占め、対象は7{,}916件、AUCは0.966であった。
            \end{abstract}
            \input{sections/results.tex}
            \end{document}
            """)
        self.write("sections/results.tex", r"""
            \section{結果}
            チオール系は18.34\%を占めた。対象は7,916件である。AUCは0.9662であった。
            """)
        self.fls("main.tex", "preamble.tex", "sections/results.tex")
        out = self.cli("crosscheck")
        self.assertIn("main.tex:4-6: 3 number(s), 2 not found elsewhere", out)
        self.assertIn("main.tex:5: 24.32\n", out)
        self.assertIn("main.tex:5: 0.966  (rounds from 0.9662 at sections/results.tex:2)", out)
        self.assertNotIn(": 7916", out)
        # Extra regions are checked against everything outside them.
        out = self.cli("crosscheck", "--region", "sections/results.tex:2-2")
        self.assertIn("main.tex:4-6: 3 number(s), 2 not found elsewhere", out)
        self.assertIn("sections/results.tex:2-2: 3 number(s), 2 not found elsewhere", out)
        self.assertIn("sections/results.tex:2: 18.34\n", out)

    def test_crosscheck_uses_markers_or_an_explicit_range_and_never_guesses(self):
        self.write("main.tex", r"""
            \documentclass{ltjsarticle}
            \begin{document}
            \textbf{Abstract.} Accuracy reached 91.5 percent.
            \section{Results}
            Accuracy reached 91.5 percent on 1,200 samples.
            \end{document}
            """)
        self.fls("main.tex")
        result =subprocess.run([sys.executable, str(CLI), "crosscheck", "--project", str(self.project)],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("cannot tell where the summary is", result.stderr)
        self.assertIn("main.tex:3-3: 1 number(s), 0 not found", self.cli("crosscheck", "--summary-range", "main.tex:3-3"))
        text = (self.project / "main.tex").read_text().replace(
            r"\textbf{Abstract.}", "% research-latex: summary-begin\n\\textbf{Abstract.}", 1).replace(
            r"\section{Results}", "% research-latex: summary-end\n\\section{Results}", 1)
        (self.project / "main.tex").write_text(text)
        self.assertIn("main.tex:3-5: 1 number(s), 0 not found", self.cli("crosscheck"))

    def test_verify_runs_registered_checks_and_lists_unsourced_numbers(self):
        self.write("main.tex", r"""
            \documentclass{ltjsarticle}
            \usepackage{biblatex}
            \begin{document}
            \section{結果}
            対象は
            7,916件である。精度は0.93であった。
            先行研究では0.88である\cite{smith2024}。
            \cite[表3]{smith2024}によれば0.81である。
            \Cref{tab:x}の値は0.75である。
            \begin{table}
            0.11 & 0.12 \\
            \end{table}
            \end{document}
            """)
        self.fls("main.tex")
        verify = (SKILL / "assets/common/verify_claims.py").read_text()
        checks = textwrap.dedent('''
            @check("cohort size", "main.tex")
            def _():
                return f"対象は{7916:,}件である"


            @check("accuracy", "main.tex")
            def _():
                return f"精度は{0.9349:.3f}であった"


            @check("slow scan", "main.tex", slow=True)
            def _():
                raise RuntimeError("must not run without --all")
            ''')
        self.write("scripts/verify_claims.py", verify.replace(
            "# ---- register checks below this line ----------------------------------------\n",
            "# ---- register checks below this line ----------------------------------------\n" + checks))
        out = self.cli("verify", expected=1)
        self.assertIn("verify_claims: 1 passed, 1 failed, 1 slow skipped", out)
        self.assertIn("main.tex does not contain: 精度は0.935であった", out)
        self.assertIn("2 sentence(s) with numbers but no", out)
        self.assertIn("main.tex:5: 対象は 7,916件である。", out)
        self.assertIn("main.tex:6: 精度は0.93であった。", out)
        self.assertIn("1 citing without a location", out)
        self.assertIn(r"main.tex:7: 先行研究では0.88である\cite{smith2024}。", out)
        self.assertNotIn("0.81", out)
        self.assertNotIn("0.11", out)
        self.assertIn("ERROR slow scan: RuntimeError", self.cli("verify", "--all", expected=1))

    def test_init_copies_an_empty_verify_skeleton_that_passes(self):
        target = self.project.parent / "fresh"
        subprocess.run([sys.executable, str(CLI), "init", "--template", "academic", "--output", str(target)],
                       check=True, capture_output=True)
        result = subprocess.run([sys.executable, str(target / "scripts/verify_claims.py")],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no checks registered", result.stdout)
        self.assertIn("% research-latex: summary-begin", (target / "main.tex").read_text())

    def test_a_second_build_is_refused_while_one_runs(self):
        self.write("main.tex", "\\documentclass{article}\n")
        with (self.project / "build/.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([sys.executable, str(CLI), "build", "--project", str(self.project)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("another build is running in this project", result.stderr)

    def test_warnings_name_the_source_file_and_lines(self):
        (self.project / "sections/09-appendix.tex").write_text("x\n")
        log = textwrap.dedent(r"""
            (./main.tex (/usr/share/texlive/texmf-dist/tex/latex/base/article.cls
            Document Class: article (./preamble.tex))
            (./sections/09-appendix.tex [12] (./build/main.aux)
            Overfull \hbox (50.23pt too wide) in paragraph at lines 34--35
            [13])
            LaTeX Warning: Reference `fig:x' on page 14 undefined on input line 88.
            Overfull \hbox (3.0pt too wide) in paragraph at lines 90--90
            )
            """)
        overfull = research_latex.log_locations(self.project, log, r"Overfull \\[hv]box")
        self.assertEqual(overfull, [
            r"sections/09-appendix.tex, lines 34--35: Overfull \hbox (50.23pt too wide) in paragraph at lines 34--35",
            r"main.tex, lines 90--90: Overfull \hbox (3.0pt too wide) in paragraph at lines 90--90",
        ])
        undefined = research_latex.log_locations(self.project, log, r"LaTeX Warning:.*(?:Reference|Citation).*undefined")
        self.assertEqual(undefined[0].split(":")[0], "main.tex, input line 88")

    def test_render_changed_writes_only_changed_pages_and_neighbours(self):
        tools = self.project.parent / "bin"
        tools.mkdir()
        for name, body in (("pdfinfo", FAKE_PDFINFO), ("pdftoppm", FAKE_PDFTOPPM)):
            (tools / name).write_text(body)
            (tools / name).chmod(0o755)
        env = {"PATH": f"{tools}{os.pathsep}{os.environ['PATH']}"}
        pdf = self.project / "report.pdf"
        pdf.write_text("\n---\n".join(f"page {n}" for n in range(1, 7)))
        rendered = self.project / "build/rendered"
        out = self.cli("render", "--changed", env=env)
        self.assertIn("rendered all 6 page(s)", out)
        self.assertEqual(len(list(rendered.glob("page-*.png"))), 6)
        pdf.write_text("\n---\n".join(f"page {n}{' edited' if n == 4 else ''}" for n in range(1, 7)))
        out = self.cli("render", "--changed", env=env)
        self.assertIn("Changed page(s): 4 of 6", out)
        self.assertEqual(sorted(p.name for p in rendered.glob("page-*.png")), ["page-3.png", "page-4.png", "page-5.png"])
        self.assertIn("No page changed", self.cli("render", "--changed", env=env))
        self.assertEqual(list(rendered.glob("page-*.png")), [])
        # A plain render records its pages too, so --changed compares against what was last looked at.
        pdf.write_text("\n---\n".join(f"page {n}" for n in range(1, 6)))
        self.cli("render", "--all", env=env)
        self.assertIn("No page changed", self.cli("render", "--changed", env=env))


if __name__ == "__main__":
    unittest.main()
