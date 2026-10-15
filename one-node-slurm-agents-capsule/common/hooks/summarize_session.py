#!/usr/bin/env python3
"""Create a minimal session summary when a run directory is available."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    run_dir = os.environ.get("AGENTRUN_DIR")
    if not run_dir:
        return 0
    artifacts = Path(run_dir) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    report = artifacts / "report.md"
    if not report.exists():
        report.write_text("# Agent Run Report\n\nNo final report was provided.\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
