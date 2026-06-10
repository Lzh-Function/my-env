#!/usr/bin/env python3
"""Reject direct compute-style commands outside a Slurm allocation."""

from __future__ import annotations

import json
import os
import re
import sys


COMPUTE_RE = re.compile(
    r"(^|[|;&]\s*)(python[0-9.]*|ipython|jupyter|pytest|torchrun|deepspeed|accelerate\s+launch)\b"
)


def load_command() -> str:
    raw = sys.stdin.read()
    if not raw.strip():
        return " ".join(sys.argv[1:])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return payload.get("tool_input", {}).get("command", "")


def main() -> int:
    command = load_command().strip()
    if not command or os.environ.get("SLURM_JOB_ID"):
        return 0
    if command.startswith(("srun ", "sbatch ")):
        return 0
    if COMPUTE_RE.search(command):
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "Compute commands must run inside a Slurm allocation.",
                },
                ensure_ascii=False,
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

