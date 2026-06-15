#!/usr/bin/env python3
"""Record that an edit happened without running formatters implicitly."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    run_dir = os.environ.get("AGENTRUN_DIR")
    if not run_dir:
        return 0
    live_dir = Path(run_dir) / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "post_edit",
        "note": "No formatter was run implicitly.",
    }
    with (live_dir / "events.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
