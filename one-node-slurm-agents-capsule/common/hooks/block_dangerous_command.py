#!/usr/bin/env python3
"""Block dangerous shell commands and file-tool access to secret resources.

Handles all agent tool formats:
  - Claude/Codex Bash:      tool_input.command
  - Claude Read/Edit/Write: tool_input.file_path
  - Codex apply_patch:      tool_input.command (the patch text; only its file headers are checked)
"""

from __future__ import annotations

import json
import re
import sys

# Secret and auth files, matched as paths. Kept to concrete file names so that
# ordinary words such as "token" (tokenizer, --max-new-tokens) or "secret" are
# not blocked. Environment variables are not covered: values passed into the
# capsule are readable by the agent by design.
SECRET_PATH_RE = re.compile(
    r"(\.ssh/|\bid_rsa\b|\bid_ed25519\b|\bauth\.json\b|\.credentials\.json\b"
    r"|(^|[\s/'\"=:])\.env(\.[\w.-]+)?($|[\s/'\";|&)])"
    r"|(^|[\s/'\"=:])secrets/|\.bashrc\b|\.workspace_rc\b)",
    re.IGNORECASE,
)
DESTROY_RE = re.compile(
    r"rm\s+-[a-zA-Z]*r[a-zA-Z]*f[a-zA-Z]*\s+[/~]"
    r"|rm\s+-[a-zA-Z]*f[a-zA-Z]*r[a-zA-Z]*\s+[/~]"
    r"|\bmkfs\b"
)
# ssh and sudo are forbidden regardless of arguments
FORBIDDEN_CMD_RE = re.compile(r"(^|[|;&]\s*)\s*(ssh|sudo)\s")

# Codex apply_patch file headers: "*** Add File: path", "*** Move to: path", ...
PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", re.MULTILINE)


def _get_targets(payload: dict) -> tuple[str, list[str]]:
    """Return (shell command, file paths) from any hook payload format."""
    inp = payload.get("tool_input", {})
    command = inp.get("command", "")
    if not isinstance(command, str):
        command = " ".join(map(str, command))
    if payload.get("tool_name") == "apply_patch" or command.lstrip().startswith("*** Begin Patch"):
        # The patch body is file content, not a command: only check the files it touches.
        return "", [m.strip() for m in PATCH_PATH_RE.findall(command)]
    path = inp.get("file_path", "")
    return command, [path] if path else []


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
        cmd, paths = _get_targets(payload)
    except json.JSONDecodeError:
        cmd, paths = raw, []

    def block(reason: str) -> int:
        print(json.dumps({"decision": "block", "reason": reason}))
        print(reason, file=sys.stderr)
        return 2

    if cmd and SECRET_PATH_RE.search(cmd):
        return block("Secret and auth files must not be accessed.")
    if cmd and DESTROY_RE.search(cmd):
        return block("Destructive system commands are not allowed.")
    if cmd and FORBIDDEN_CMD_RE.search(cmd):
        return block("ssh and sudo are not allowed.")
    for path in paths:
        if SECRET_PATH_RE.search(path):
            return block("Reading or writing secret files is forbidden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
