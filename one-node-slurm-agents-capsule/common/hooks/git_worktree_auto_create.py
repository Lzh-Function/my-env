#!/usr/bin/env python3
"""PostToolUse: after branch creation, auto-create a git worktree at ../<branch>."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def extract_branch_name(cmd: str) -> str:
    m = re.search(r"git\s+checkout\s+-[bB]\s+(\S+)", cmd)
    if m:
        return re.sub(r"[;|&]", "", m.group(1))
    m = re.search(r"git\s+switch\s+(?:-c|--create)\s+(\S+)", cmd)
    if m:
        return re.sub(r"[;|&]", "", m.group(1))
    return ""


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        cmd = payload.get("tool_input", {}).get("command", "")
    except json.JSONDecodeError:
        cmd = raw

    branch = extract_branch_name(cmd.strip())
    if not branch:
        return 0

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        repo_root = result.stdout.strip()
    except Exception:
        return 0

    if not repo_root:
        return 0

    worktree_path = str(Path(repo_root).parent / branch)

    list_result = subprocess.run(
        ["git", "-C", repo_root, "worktree", "list"],
        capture_output=True, text=True, timeout=5,
    )
    if worktree_path in list_result.stdout:
        return 0

    if Path(worktree_path).exists():
        print(f"警告: {worktree_path} は既に存在するためworktreeの作成をスキップしました。", file=sys.stderr)
        return 0

    result = subprocess.run(
        ["git", "-C", repo_root, "worktree", "add", worktree_path, branch],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode == 0:
        print(f"worktree を作成しました: {worktree_path}")
    else:
        print(f"worktree 作成失敗: {result.stderr.strip()}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
