#!/usr/bin/env python3
"""Block dangerous shell commands and file-tool access to secret resources.

Handles all three agent tool formats:
  - Claude/Codex Bash:      tool_input.command
  - Claude Read/Edit/Write: tool_input.file_path
  - Antigravity run_command: toolCall.args.CommandLine
  - Antigravity view/write:  toolCall.args.AbsolutePath / TargetFile
"""

from __future__ import annotations

import json
import re
import sys

# Patterns for dangerous content in shell command strings
SECRET_CMD_RE = re.compile(
    r"(\.ssh|id_rsa|id_ed25519|auth\.json|\.env\b|token|secret)", re.IGNORECASE
)
DESTROY_RE = re.compile(
    r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+[/~]"
    r"|rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+[/~]"
    r"|\bmkfs\b"
)
# ssh and sudo are forbidden regardless of arguments
FORBIDDEN_CMD_RE = re.compile(r"(^|[|;&]\s*)\s*(ssh|sudo)\s")

# Patterns for secret file paths (for file-tool calls with explicit file_path args)
SECRET_PATH_RE = re.compile(
    r"(\.ssh/|id_rsa|id_ed25519|auth\.json|\.env(\.|/|$)|secrets/|\.bashrc|\.workspace_rc)",
    re.IGNORECASE,
)


def _get_targets(payload: dict) -> tuple[str, str]:
    """Return (command, file_path) from any hook payload format."""
    if "toolCall" in payload:
        args = payload["toolCall"].get("args", {})
        return (
            args.get("CommandLine", ""),
            args.get("AbsolutePath") or args.get("TargetFile") or "",
        )
    inp = payload.get("tool_input", {})
    return inp.get("command", ""), inp.get("file_path", "")


def main() -> int:
    raw = sys.stdin.read()
    decision = "deny"
    try:
        payload = json.loads(raw)
        if "toolCall" not in payload:
            decision = "block"
        cmd, path = _get_targets(payload)
    except json.JSONDecodeError:
        cmd, path = raw, ""

    if cmd and SECRET_CMD_RE.search(cmd):
        print(json.dumps({"decision": decision, "reason": "Secret and auth material must not be accessed."}))
        return 2
    if cmd and DESTROY_RE.search(cmd):
        print(json.dumps({"decision": decision, "reason": "Destructive system commands are not allowed."}))
        return 2
    if cmd and FORBIDDEN_CMD_RE.search(cmd):
        print(json.dumps({"decision": decision, "reason": "ssh and sudo are not allowed."}))
        return 2
    if path and SECRET_PATH_RE.search(path):
        print(json.dumps({"decision": decision, "reason": "Reading or writing secret files is forbidden."}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
