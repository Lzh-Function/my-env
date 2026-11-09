#!/usr/bin/env python3
"""Block dangerous git ops: rebase and direct .git access. Merge, pull and force-push are allowed."""

from __future__ import annotations

import json
import re
import sys


def block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 2


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

    if re.search(r"git\s+rebase\b", cmd) and not re.search(r"git\s+rebase\s+--(abort|continue|quit|skip)\b", cmd):
        return block("git rebase は禁止されています。ユーザーに委ねてください。")

    if re.search(r"(^|\s|/)\.git(/|\s|$)", cmd):
        return block(".git ディレクトリへの直接操作は禁止されています。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
