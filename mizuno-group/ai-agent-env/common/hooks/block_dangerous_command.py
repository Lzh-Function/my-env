#!/usr/bin/env python3
"""Block Bash commands that access secrets or perform destructive operations."""

from __future__ import annotations

import json
import re
import sys

SECRET_RE = re.compile(
    r"(\.ssh|id_rsa|id_ed25519|auth\.json|\.env\b|token|secret)", re.IGNORECASE
)

# Matches rm -rf / or rm -rf ~ (and variants like rm -fr, rm --recursive --force)
DESTROY_RE = re.compile(
    r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+[/~]"
    r"|rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+[/~]"
    r"|\bmkfs\b"
)


def main() -> int:
    raw = sys.stdin.read()
    command = raw
    try:
        payload = json.loads(raw)
        command = payload.get("tool_input", {}).get("command", raw)
    except json.JSONDecodeError:
        pass
    if SECRET_RE.search(command):
        print(
            json.dumps(
                {"decision": "block", "reason": "Secret and auth material must not be read."}
            )
        )
        return 2
    if DESTROY_RE.search(command):
        print(
            json.dumps(
                {"decision": "block", "reason": "Destructive system commands are not allowed."}
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

