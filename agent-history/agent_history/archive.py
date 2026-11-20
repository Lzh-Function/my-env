"""Archive local conversations as Markdown and index them in SQLite.

Layout under the history root (~/agent-history, or AGENT_HISTORY_DIR):
  archives/<provider>/<session>.md   one Markdown snapshot per conversation
  index.sqlite3                      list/search index, one row per conversation
  titles.json                        names given with `agent-history rename`
Only conversations whose files changed since the last archive are rendered again, and
only the lines appended since then are read: each transcript's parser state, read offset
and Markdown so far are kept in cache/ (a rewritten file is read again from the start).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import shutil
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .sources import Session, all_sessions
from .transcripts import PARSERS, EventMessage, atomic_text, clean, fence, json_text

TAIL = 4096  # bytes before the read offset whose hash tells an appended file from a rewritten one

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


class Transcript:
    """One transcript file rendered incrementally, with its cache next to the archive."""

    def __init__(self, root: Path, session: Session, path: Path):
        key = hashlib.sha256(str(path).encode()).hexdigest()[:16]
        self.cache = root / "cache" / session.archive_id
        self.state_path = self.cache / f"{key}.json"
        self.body_path = self.cache / f"{key}.md"
        self.events_path = self.cache / f"{key}.events.md"  # Codex: messages logged only as events
        self.path = path
        self.provider = session.provider

    def tail_hash(self, stream, offset):
        stream.seek(max(0, offset - TAIL))
        return hashlib.sha256(stream.read(offset - max(0, offset - TAIL))).hexdigest()

    def update(self):
        """Read what was appended since last time and return the parser."""
        try:
            saved = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        stat = self.path.stat()
        with self.path.open("rb") as stream:
            if (not saved or saved["inode"] != stat.st_ino or saved["offset"] > stat.st_size
                    or saved["tail"] != self.tail_hash(stream, saved["offset"])
                    or not self.body_path.is_file()):
                saved = {"offset": 0, "parser": None}
                self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.body_path.write_text("")
                self.events_path.unlink(missing_ok=True)
            parser = PARSERS[self.provider](self.path, saved["parser"])
            stream.seek(saved["offset"])
            data = stream.read()
            # A last line without its newline is still being written: leave it for next time.
            complete = data[:data.rfind(b"\n") + 1]
            plain, events = [], []
            for number, line in enumerate(complete.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    raise ValueError(f"{self.path.name}: invalid JSONL record after byte {saved['offset']}") from None
                if not isinstance(record, dict):
                    raise ValueError(f"{self.path.name}: expected a JSON object")
                for part in parser.feed(record):
                    events.append(part)
                    if not isinstance(part, EventMessage):
                        plain.append(part)
            parser.finish()
            offset = saved["offset"] + len(complete)
            if len(events) != len(plain) and not self.events_path.exists():
                # The first event-only message: the full body so far is the plain body so far.
                shutil.copyfile(self.body_path, self.events_path)
            with self.body_path.open("a", encoding="utf-8") as body:
                body.write("".join(plain))
            if self.events_path.exists():
                with self.events_path.open("a", encoding="utf-8") as body:
                    body.write("".join(events))
            state = {"inode": stat.st_ino, "offset": offset, "tail": self.tail_hash(stream, offset),
                     "parser": parser.state()}
        temporary = self.state_path.with_name(self.state_path.name + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.state_path)
        return parser

    def body(self, parser):
        # Old Codex logs carry messages only as events; use them when there is nothing else.
        if getattr(parser, "has_messages", True) is False and self.events_path.exists():
            return self.events_path.read_text(encoding="utf-8")
        return self.body_path.read_text(encoding="utf-8")


def render(root: Path, session: Session) -> tuple[str, dict]:
    """The archive Markdown for one conversation, and its metadata."""
    warnings, parts, transcripts = set(), [], []
    for path, role in [(session.transcript, "worker"), *((p, "subagent") for p in session.subagents)]:
        transcript = Transcript(root, session, path)
        parser = transcript.update()
        warnings |= parser.warnings
        if role == "worker" and session.provider == "claude":
            session.cwd, session.title = parser.cwd, parser.title
        metadata = dict(parser.metadata, file=str(path), provider=session.provider, role=role)
        transcripts.append(metadata)
        name = session.session_id if role == "worker" else path.stem
        parts.append(f"\n## Session: {name} ({role}, {session.provider})\n\n{fence(json_text(metadata), 'json')}"
                     + transcript.body(parser))
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
    if force:
        shutil.rmtree(root / "cache" / session.archive_id, ignore_errors=True)
    markdown, metadata = render(root, session)
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
