"""Archive local conversations as Markdown and index them in SQLite.

Layout under the history root (~/agent-history, or AGENT_HISTORY_DIR):
  archives/<provider>/<session>.md   one Markdown snapshot per conversation
  index.sqlite3                      list/search index, one row per conversation
  titles.json                        names given with `agent-history rename`
Only conversations whose files changed since the last archive are rendered again.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .sources import Session, all_sessions
from .transcripts import (antigravity_transcript, atomic_text, claude_transcript, clean, codex_transcript,
                          fence, json_text)

SCHEMA = """CREATE TABLE IF NOT EXISTS conversations (
    archive_id TEXT PRIMARY KEY, provider TEXT NOT NULL, session_id TEXT NOT NULL, cwd TEXT NOT NULL,
    title TEXT NOT NULL, markdown_path TEXT NOT NULL, metadata_json TEXT NOT NULL, markdown TEXT NOT NULL,
    signature TEXT NOT NULL, updated_at TEXT NOT NULL)"""


def history_root() -> Path:
    configured = os.environ.get("AGENT_HISTORY_DIR")
    return (Path(configured).expanduser() if configured else Path.home() / "agent-history").resolve()


@contextmanager
def locked():
    """One writer at a time: Stop hooks of several open sessions may fire together."""
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / ".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield root


def connect(root: Path) -> sqlite3.Connection:
    database = root / "index.sqlite3"
    db = sqlite3.connect(database, timeout=60)
    os.chmod(database, 0o600)
    db.execute(SCHEMA)
    return db


def render(session: Session) -> tuple[str, dict]:
    """The archive Markdown for one conversation, and its metadata."""
    warnings, parts, transcripts = set(), [], []
    for path, role in [(session.transcript, "worker"), *((p, "subagent") for p in session.subagents)]:
        if session.provider == "codex":
            metadata, body = codex_transcript(path, warnings)
        elif session.provider == "claude":
            metadata, body = claude_transcript(path, warnings)
        else:
            metadata, body = antigravity_transcript(path, warnings)
        metadata.update(file=str(path), provider=session.provider, role=role)
        transcripts.append(metadata)
        name = session.session_id if role == "worker" else path.stem
        parts.append(f"\n## Session: {name} ({role}, {session.provider})\n\n{fence(json_text(metadata), 'json')}{body}")
    info = {"provider": session.provider, "session_id": session.session_id, "cwd": session.cwd,
            "title": session.title, "archive_id": session.archive_id,
            "archived_at": datetime.now(timezone.utc).isoformat(), "warnings": sorted(warnings)}
    markdown = "# Conversation archive\n\n" + fence(json_text(info), "json")
    markdown += "".join(parts) if parts else "\nNo conversation records were found.\n"
    if warnings:
        markdown += "\n## Archive notes\n\n" + "".join(f"- {clean(w)}\n" for w in sorted(warnings))
    return markdown, dict(info, transcripts=transcripts)


def store(db: sqlite3.Connection, root: Path, session: Session, force: bool = False) -> str:
    """Archive one conversation unless it is unchanged; returns "new", "updated" or "same"."""
    signature = json.dumps(session.signature())
    row = db.execute("SELECT signature FROM conversations WHERE archive_id = ?", (session.archive_id,)).fetchone()
    if row and row[0] == signature and not force:
        return "same"
    session.load()
    markdown, metadata = render(session)
    path = root / "archives" / session.provider / f"{session.session_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_text(path, markdown)
    os.chmod(path, 0o600)
    db.execute("INSERT OR REPLACE INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        session.archive_id, session.provider, session.session_id, session.cwd, session.title, str(path),
        json.dumps(metadata, ensure_ascii=False), markdown, signature, metadata["archived_at"]))
    db.commit()
    return "updated" if row else "new"


def sync(providers, force: bool = False, quiet: bool = False) -> dict:
    """Archive every local conversation that is new or changed."""
    counts = {"new": 0, "updated": 0, "same": 0, "failed": 0}
    with locked() as root:
        db = connect(root)
        try:
            for session in all_sessions(providers):
                try:
                    counts[store(db, root, session, force)] += 1
                except (OSError, ValueError) as error:
                    counts["failed"] += 1
                    if not quiet:
                        print(f"保存できませんでした: {session.provider} {session.session_id}（{error}）")
        finally:
            db.close()
    return counts


def sync_one(session: Session) -> str:
    with locked() as root:
        db = connect(root)
        try:
            return store(db, root, session)
        finally:
            db.close()
