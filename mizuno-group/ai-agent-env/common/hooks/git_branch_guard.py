#!/usr/bin/env python3
"""Block dangerous git ops: checkout/switch to main, merge, rebase, direct .git access."""

from __future__ import annotations

import json
import re
import sys


def block(reason: str, decision: str = "deny") -> int:
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))
    return 2


def main() -> int:
    raw = sys.stdin.read()
    decision = "deny"
    try:
        payload = json.loads(raw)
        if "toolCall" in payload:
            cmd = payload["toolCall"].get("args", {}).get("CommandLine", "")
        else:
            decision = "block"
            cmd = payload.get("tool_input", {}).get("command", "")
    except json.JSONDecodeError:
        cmd = raw

    cmd = cmd.strip()
    if not cmd:
        return 0

    if re.search(r"git\s+merge\b", cmd) and not re.search(r"git\s+merge\s+--(abort|continue|quit)\b", cmd):
        return block("git merge は禁止されています。ユーザーに委ねてください。", decision)

    if re.search(r"git\s+rebase\b", cmd) and not re.search(r"git\s+rebase\s+--(abort|continue|quit|skip)\b", cmd):
        return block("git rebase は禁止されています。ユーザーに委ねてください。", decision)

    if re.search(r"(^|\s|/)\.git(/|\s|$)", cmd):
        return block(".git ディレクトリへの直接操作は禁止されています。", decision)

    if re.search(r"git\s+push\b", cmd):
        return block("git push は禁止されています。ユーザーが最終的な push を実行してください。", decision)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
