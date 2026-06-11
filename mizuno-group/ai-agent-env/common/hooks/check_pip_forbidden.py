#!/usr/bin/env python3
"""Block direct pip invocations; use uv instead."""

from __future__ import annotations

import json
import re
import sys

PIP_RE = re.compile(r"(^|[|;&]\s*)pip[0-9.]*\s", re.IGNORECASE)


def main() -> int:
    raw = sys.stdin.read()
    command = raw
    try:
        payload = json.loads(raw)
        command = payload.get("tool_input", {}).get("command", raw)
    except json.JSONDecodeError:
        pass
    if PIP_RE.search(command):
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "pip is forbidden. Use uv instead (uv add / uv sync / uv run).",
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
