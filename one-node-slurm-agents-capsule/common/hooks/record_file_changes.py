#!/usr/bin/env python3
"""Record which workspace files changed after each tool call, one JSON line per file.

Runs after file-edit tools and after shell commands, so edits made with sed, redirects,
scripts or git are caught as well as the CLI's own edit tools. It does not read the
tool's arguments: it compares the files themselves with what it saw last time (or with
HEAD for a file it has not seen), so it costs the agent nothing and prints nothing.

Each line in /runs/live/events.jsonl:
  {"ts": ..., "event": "file_change", "file": "src/a.py", "added": 3, "removed": 1}
plus "created": true / "deleted": true / "binary": true when that applies.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN = Path(os.environ.get("AGENTRUN_DIR", "/runs"))
WORKSPACE = Path(os.environ.get("AGENTRUN_WORKSPACE", "/workspace"))
# Last-seen copies of changed files; kept in the run's scratch, never in the workspace.
STORE = RUN / "scratch/.file-changes"
TEXT_LIMIT = 2 * 1024 * 1024  # larger files are reported as changed without counting lines
MAX_FILES = 2000  # a command that touches more than this is summarized as one line


def local_now() -> str:
    """ISO time in Japan time (AGENTRUN_TIMEZONE to change), like the rest of agentrun's logs."""
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(os.environ.get("AGENTRUN_TIMEZONE") or "Asia/Tokyo")
    except Exception:  # noqa: BLE001 - no tz database in the image: use Japan time
        zone = timezone(timedelta(hours=9))
    return datetime.now(zone).isoformat(timespec="seconds")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(WORKSPACE), "-c", "core.quotepath=false", *args],
                          capture_output=True, timeout=20, check=False)


def changed_paths() -> list[str] | None:
    """Tracked and untracked files that differ from HEAD; None outside a Git repository."""
    result = git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result.returncode:
        return None
    paths, entries = [], result.stdout.decode("utf-8", "surrogateescape").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            index += 1  # the next entry is the old name of a rename or copy
        paths.append(path)
    return paths


def head_content(path: str) -> bytes | None:
    result = git("show", "HEAD:" + path)
    return result.stdout if result.returncode == 0 else None


def lines(data: bytes) -> list[str] | None:
    if len(data) > TEXT_LIMIT or b"\0" in data[:8192]:
        return None
    return data.decode("utf-8", "replace").splitlines()


def main() -> int:
    sys.stdin.read()  # the tool payload is not needed
    live = RUN / "live"
    live.mkdir(parents=True, exist_ok=True)
    index_path = STORE / "index.json"
    try:
        seen = json.loads(index_path.read_text())
    except (OSError, ValueError):
        seen = {}
    paths = changed_paths()
    if paths is None:
        return 0  # not a Git workspace: nothing to compare against
    # Files seen before but now back at HEAD (or deleted) must be checked too.
    candidates = sorted(set(paths) | set(seen))
    now = local_now()
    events = []
    if len(candidates) > MAX_FILES:
        events.append({"ts": now, "event": "file_change", "file": None, "files": len(candidates),
                       "note": "too many changed files to count line by line"})
        candidates = []
    STORE.mkdir(parents=True, exist_ok=True)
    for path in candidates:
        target = WORKSPACE / path
        if {".git", "__pycache__"} & set(Path(path).parts):
            continue  # Git internals and Python's bytecode cache are not edits
        current = target.read_bytes() if target.is_file() and not target.is_symlink() else None
        stored = STORE / "files" / hashlib.sha256(path.encode()).hexdigest()
        head = head_content(path)
        # seen: "copy" = last content kept in the store, "absent" = last seen deleted.
        state = seen.get(path)
        previous = None if state == "absent" else stored.read_bytes() if state == "copy" else head
        if current == previous:
            continue
        event = {"ts": now, "event": "file_change", "file": path}
        old, new = lines(previous or b""), lines(current or b"")
        if old is None or new is None:
            event["binary"] = True
        else:
            diff = list(difflib.unified_diff(old, new, lineterm="", n=0))
            event["added"] = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
            event["removed"] = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
        if previous is None:
            event["created"] = True
        if current is None:
            event["deleted"] = True
        events.append(event)
        stored.unlink(missing_ok=True)
        if current == head:
            seen.pop(path, None)  # back to HEAD: HEAD is the reference again
        elif current is None:
            seen[path] = "absent"
        else:
            stored.parent.mkdir(parents=True, exist_ok=True)
            stored.write_bytes(current)
            seen[path] = "copy"
    index_path.write_text(json.dumps(seen))
    if events:
        with (live / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.writelines(json.dumps(event, ensure_ascii=False) + "\n" for event in events)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 - a bookkeeping hook must never stop the agent's work
        try:
            with (RUN / "live/events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"ts": local_now(),
                                         "event": "file_change_error", "error": str(error)[:300]}) + "\n")
        except OSError:
            pass
        sys.exit(0)
