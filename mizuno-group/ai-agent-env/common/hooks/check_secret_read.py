#!/usr/bin/env python3
"""Block Read tool access to secret files (SSH keys, .env, auth tokens)."""

from __future__ import annotations

import json
import re
import sys

SECRET_PATH_RE = re.compile(
    r"(\.ssh/|id_rsa|id_ed25519|auth\.json|\.env(\.|/|$)|secrets/)",
    re.IGNORECASE,
)


def main() -> int:
    raw = sys.stdin.read()
    file_path = raw
    try:
        payload = json.loads(raw)
        file_path = payload.get("tool_input", {}).get("file_path", raw)
    except json.JSONDecodeError:
        pass
    if SECRET_PATH_RE.search(str(file_path)):
        print(
            json.dumps(
                {
                    "decision": "block",
                    "reason": "Reading secret or auth files is forbidden.",
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
