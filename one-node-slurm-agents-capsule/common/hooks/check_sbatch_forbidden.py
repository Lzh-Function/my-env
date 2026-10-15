#!/usr/bin/env python3
"""Block sbatch/salloc submission from inside a Slurm allocation (no nested jobs)."""

from __future__ import annotations

import json
import os
import re
import sys

SUBMIT_RE = re.compile(r"(^|[|;&]\s*)(sbatch|salloc)\b")


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        return 0
    raw = sys.stdin.read()
    command = ""
    decision = "deny"
    try:
        payload = json.loads(raw)
        if "toolCall" in payload:
            command = payload["toolCall"].get("args", {}).get("CommandLine", "")
        else:
            decision = "block"
            command = payload.get("tool_input", {}).get("command", raw)
    except json.JSONDecodeError:
        command = raw
    if SUBMIT_RE.search(command):
        print(json.dumps({"decision": decision, "reason": "Cannot submit Slurm jobs from inside a Slurm allocation."}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
