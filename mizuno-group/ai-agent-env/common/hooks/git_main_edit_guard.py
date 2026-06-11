#!/usr/bin/env python3
"""Block edits to files on main/master branch unless user explicitly confirms."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


BYPASS_FILE = Path("/tmp/claude_allow_main_edit")


def main() -> int:
    if BYPASS_FILE.exists():
        return 0

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        inp = payload.get("tool_input", {})
        file_path = inp.get("file_path") or inp.get("notebook_path", "")
    except json.JSONDecodeError:
        return 0

    if not file_path:
        return 0

    directory = str(Path(file_path).parent)
    try:
        result = subprocess.run(
            ["git", "-C", directory, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        branch = result.stdout.strip()
    except Exception:
        return 0

    if not branch or branch == "HEAD":
        return 0

    if branch in ("main", "master"):
        print(json.dumps({
            "decision": "block",
            "reason": (
                f"編集対象ファイル ({file_path}) は {branch} ブランチにあります。"
                "ユーザーに確認し、指示に従ってください: "
                "(1) mainに直接編集してよい → あなたが `touch /tmp/claude_allow_main_edit` を実行してから編集を再試行 / "
                "(2) 新しいブランチを切ってほしい → ブランチ名を聞いてブランチ作成後に編集 / "
                "(3) 中止"
            ),
        }, ensure_ascii=False))
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
