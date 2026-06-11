#!/usr/bin/env python3
"""Block direct compute-heavy commands on a SLURM login node."""

from __future__ import annotations

import json
import os
import re
import sys

COMPUTE_RE = re.compile(
    r"(^|[|;&\s])\s*"
    r"(python[0-9.]*|python3\.[0-9]+|ipython"
    r"|jupyter(\s+(notebook|lab|console|nbconvert|execute))?"
    r"|pytest|torchrun|deepspeed"
    r"|accelerate\s+launch|lightning\s+run"
    r"|vina|gnina|smina|autodock|xtb|crest|mmpbsa\.py)\b",
    re.IGNORECASE,
)

ENV_PREFIX_RE = re.compile(r"^([A-Z_][A-Z_0-9]*=[^\s]*\s+)+")
VERSION_RE = re.compile(r"\s+(-V|--version|--help|-h)\s*$")


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        cmd = payload.get("tool_input", {}).get("command", "")
    except json.JSONDecodeError:
        cmd = raw

    cmd = cmd.strip()
    if not cmd:
        return 0

    if os.environ.get("SLURM_JOB_ID"):
        return 0

    if re.match(r"^\s*(srun|sbatch)\b", cmd):
        return 0

    stripped = ENV_PREFIX_RE.sub("", cmd)

    if not COMPUTE_RE.search(stripped):
        return 0

    if VERSION_RE.search(cmd):
        return 0

    first_word = (stripped.split() or cmd.split() or ["?"])[0]
    print(json.dumps({
        "decision": "block",
        "reason": (
            f"ログインノードでの直接実行は禁止です: {first_word} は"
            "srunまたはsbatchで投入してください。"
            "パーティション等の引数はプロジェクトの./CLAUDE.mdを確認してください。"
        ),
    }, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
