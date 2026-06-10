#!/usr/bin/env python3
"""Reject commands that attempt to read obvious secret material."""

from __future__ import annotations

import json
import re
import sys


SECRET_RE = re.compile(r"(\.ssh|id_rsa|id_ed25519|auth\.json|\.env\b|token|secret)", re.IGNORECASE)


def main() -> int:
    raw = sys.stdin.read()
    command = raw
    try:
        payload = json.loads(raw)
        command = payload.get("tool_input", {}).get("command", raw)
    except json.JSONDecodeError:
        pass
    if SECRET_RE.search(command):
        print(json.dumps({"decision": "block", "reason": "Secret and auth material must not be read."}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

