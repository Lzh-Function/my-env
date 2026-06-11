#!/usr/bin/env python3
"""Ensure a venv is activated in srun/sbatch Python jobs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _session_env_file() -> Path:
    md5 = hashlib.md5(os.getcwd().encode()).hexdigest()[:8]
    return Path(f"/tmp/claude_python_env_{md5}")


def get_session_env() -> str:
    env_file = _session_env_file()
    if env_file.exists():
        path = env_file.read_text().strip()
        if path and Path(f"{path}/bin/activate").exists():
            return path
    return ""


def list_envs() -> str:
    try:
        result = subprocess.run(
            ["find", ".", "-maxdepth", "5", "-name", "activate", "-path", "*/bin/activate"],
            capture_output=True, text=True, timeout=10,
        )
        paths = sorted(p.replace("/bin/activate", "") for p in result.stdout.strip().splitlines())
        return "  /  ".join(paths) or "(none found)"
    except Exception:
        return "(search failed)"


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

    is_srun = bool(re.match(r"^\s*srun\b", cmd))
    is_sbatch = bool(re.match(r"^\s*sbatch\b", cmd))
    if not is_srun and not is_sbatch:
        return 0

    env = get_session_env()
    env_file = str(_session_env_file())

    if is_srun:
        if not re.search(r"\bpython[0-9.]*\b", cmd):
            return 0
        if "source" in cmd and "activate" in cmd:
            return 0
        if env:
            return block(
                f"srunコマンドにsource activateがありません。以下の形式で再試行してください: "
                f'srun <options> bash -c "source {env}/bin/activate && python ..."'
            )
        return block(
            f"srunコマンドにsource activateがなく、使用するvenvが未設定です。"
            f"利用可能なenv: {list_envs()}。"
            f"ユーザーにどのenvを使うか確認し、`echo '<パス>' > {env_file}` を実行してから再試行してください。"
        )

    # sbatch
    script_match = re.search(r"[^\s]+\.sh\b", cmd)
    if not script_match:
        return 0
    script_path = Path(script_match.group(0))
    if not script_path.exists():
        return 0
    script_text = script_path.read_text(errors="replace")
    if "python" not in script_text:
        return 0
    if "source" in script_text and "activate" in script_text:
        return 0
    if env:
        return block(
            f"ジョブスクリプト({script_path})にsource activateがありません。"
            f"python呼び出しの前に `source {env}/bin/activate` を追記してください。"
        )
    return block(
        f"ジョブスクリプト({script_path})にsource activateがなく、使用するvenvが未設定です。"
        f"利用可能なenv: {list_envs()}。"
        f"ユーザーにどのenvを使うか確認し、`echo '<パス>' > {env_file}` を実行してからスクリプトに追記して再試行してください。"
    )


if __name__ == "__main__":
    raise SystemExit(main())
