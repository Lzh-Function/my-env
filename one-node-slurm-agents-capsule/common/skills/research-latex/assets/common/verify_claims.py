#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""Recompute the numbers quoted in the prose and confirm the .tex still says them.

Tables generated from data stay right; numbers typed into sentences go stale
when the data changes. Register one check per load-bearing prose number:
the check recomputes the value from primary data and returns the exact text
that must appear in the named .tex file (number, unit, rounding and the
words around it). Comparison ignores whitespace and TeX comments only.

`research_latex.py build` and `verify` run this file with `uv run --script`,
so list packages the checks need (pandas, rdkit, ...) in `dependencies`
above. Checks registered with slow=True run only with `--all`.

    @check("cohort size in the methods", "main.tex")
    def _():
        rows = sum(1 for _ in open(PROJECT / "data/cohort.csv")) - 1
        return f"対象は{rows:,}件である"

Compute from unrounded values and round once: a difference of two displayed
figures (0.6674 - 0.2665) can disagree with the true difference (0.4010).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
CHECKS: list[tuple[str, str, bool, Callable[[], str]]] = []


def check(name: str, tex: str, slow: bool = False):
    """Register a check. The callable returns the exact string the .tex must hold."""
    def deco(fn: Callable[[], str]) -> Callable[[], str]:
        CHECKS.append((name, tex, slow, fn))
        return fn
    return deco


# ---- register checks below this line ----------------------------------------


# ---- runner -------------------------------------------------------------------

def normalized(text: str) -> str:
    text = "\n".join(re.sub(r"(?<!\\)%.*", "", line) for line in text.splitlines())
    return re.sub(r"\s+", "", text)


def main() -> int:
    global PROJECT
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", type=Path, default=PROJECT)
    parser.add_argument("--all", action="store_true", help="also run slow checks")
    parser.add_argument("--only", default="", help="run checks whose name contains this text")
    options = parser.parse_args()
    PROJECT = options.project.resolve()
    if not CHECKS:
        print("verify_claims: no checks registered yet")
        return 0
    texts: dict[str, str] = {}
    passed = failed = skipped = 0
    for name, tex, slow, fn in CHECKS:
        if options.only not in name:
            continue
        if slow and not options.all:
            skipped += 1
            continue
        try:
            expected = fn()
            if not isinstance(expected, str) or not expected.strip():
                raise TypeError(f"check must return the non-empty text to find, got {expected!r}")
            if tex not in texts:
                texts[tex] = normalized((PROJECT / tex).read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 - report every broken check, not only the first
            print(f"ERROR {name}: {type(error).__name__}: {error}")
            failed += 1
            continue
        if normalized(expected) in texts[tex]:
            passed += 1
        else:
            print(f"FAIL  {name}\n      {tex} does not contain: {expected}")
            failed += 1
    print(f"verify_claims: {passed} passed, {failed} failed, {skipped} slow skipped"
          + (" (run with --all)" if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
