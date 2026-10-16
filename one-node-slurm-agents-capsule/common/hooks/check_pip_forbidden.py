#!/usr/bin/env python3
"""Block direct pip invocations; use uv instead."""

from __future__ import annotations

import json
import re
import sys

# Direct pip invocations are forbidden entirely
_DIRECT_PIP_RE = re.compile(r"(^|[|;&]\s*)pip[0-9.]*\s", re.IGNORECASE)
# uv pip install/uninstall/sync/compile are forbidden; uv pip list/show/freeze are OK
_UV_PIP_MUTATE_RE = re.compile(
    r"(^|[|;&]\s*)uv\s+pip\s+(?!list\b|show\b|freeze\b|check\b)",
    re.IGNORECASE,
)


def _is_forbidden(command: str) -> bool:
    return bool(_DIRECT_PIP_RE.search(command) or _UV_PIP_MUTATE_RE.search(command))


def main() -> int:
    raw = sys.stdin.read()
    command = ""
    try:
        payload = json.loads(raw)
        command = payload.get("tool_input", {}).get("command", raw)
    except json.JSONDecodeError:
        command = raw
    if _is_forbidden(command):
        print(json.dumps({"decision": "block", "reason": "pip is forbidden. Use uv instead (uv add / uv sync / uv run). uv pip install is also forbidden."}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
