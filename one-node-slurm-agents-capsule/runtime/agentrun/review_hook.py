#!/usr/bin/env python3
"""PreToolUse hook for the Antigravity reviewer: allow only reads inside one review input."""

import json
import sys
from pathlib import Path

READ_TOOLS = {
    "read_file", "view_file", "view_file_outline", "view_code_item", "view_content_chunk",
    "view_image", "list_dir", "find_by_name", "grep_search",
}
# finish submits the --json-schema answer and has no side effects.
ANSWER_TOOLS = {"finish"}
PATH_KEYS = ("file_path", "path", "AbsolutePath", "TargetFile", "SearchPath", "SearchDirectory",
             "DirectoryPath", "FilePath")
LIST_KEYS = ("paths", "files", "ImagePaths")


def decide(payload, root):
    call = payload.get("toolCall")
    if not isinstance(call, dict):
        raise ValueError("toolCall is missing")
    tool, args = call.get("name"), call.get("args", {})
    if tool in ANSWER_TOOLS:
        return
    if tool not in READ_TOOLS or not isinstance(args, dict):
        raise ValueError(f"the reviewer may only read its input ({tool})")
    paths = [args[key] for key in PATH_KEYS if key in args]
    for key in LIST_KEYS:
        if key in args:
            if not isinstance(args[key], list):
                raise ValueError("path list is malformed")
            paths.extend(args[key])
    for value in paths:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("path is malformed")
        path = Path(value).expanduser()
        if not (path if path.is_absolute() else root / path).resolve().is_relative_to(root):
            raise ValueError("the reviewer may only read its input: " + value)


def main():
    result = {"decision": "allow"}
    try:
        root = Path(sys.argv[1]).resolve()
        raw = sys.stdin.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("hook input is too large")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be a JSON object")
        decide(payload, root)
    except Exception as error:  # noqa: BLE001 -- any failure denies the tool call
        result = {"decision": "deny", "reason": "agentrun review policy: " + str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
