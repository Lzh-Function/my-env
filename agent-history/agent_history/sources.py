"""Find the conversations each CLI keeps under the user's home directory.

One conversation is one native session: a Claude Code session file (with its subagent
files), a Codex rollout, or an Antigravity conversation. Nothing here writes anywhere.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROVIDERS = ("claude", "codex", "antigravity")
HEAD_BYTES = 256 * 1024  # titles and working directories are near the start of a transcript


@dataclass
class Session:
    provider: str
    session_id: str
    transcript: Path  # the main transcript
    subagents: list[Path] = field(default_factory=list)
    cwd: str = ""
    title: str = ""
    details: object = None  # fills cwd and title on demand when that needs a full read

    def load(self) -> None:
        if self.details:
            self.details(self)
            self.details = None

    @property
    def archive_id(self) -> str:
        return f"{self.provider}-{self.session_id}"

    @property
    def files(self) -> list[Path]:
        return [self.transcript, *self.subagents]

    def signature(self) -> list:
        """What changes whenever the conversation does: each file's size and modification time,
        plus the name and working directory when they come from elsewhere (Codex, Antigravity
        write those a moment after the turn ends)."""
        result = [] if self.details else [["title", self.title], ["cwd", self.cwd]]
        for path in self.files:
            try:
                stat = path.stat()
            except OSError:
                continue
            result.append([str(path), stat.st_size, stat.st_mtime_ns])
        return result


def claude_root() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


def codex_root() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()


def agy_root() -> Path:
    return Path.home() / ".gemini/antigravity-cli"


def head_records(path: Path, limit: int = HEAD_BYTES):
    """JSON objects from the first part of a JSONL file; a cut last line is skipped."""
    try:
        with path.open("rb") as stream:
            data = stream.read(limit)
    except OSError:
        return
    for line in data.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            yield value


def all_records(path: Path):
    try:
        with path.open("rb") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


# --- Claude Code: <config>/projects/<project>/<session>.jsonl, subagents in <session>/subagents/

def claude_details(session: Session) -> None:
    """Working directory and title; titles can be anywhere in the file, so it is read whole."""
    custom = ai = ""
    for record in all_records(session.transcript):
        if not session.cwd and isinstance(record.get("cwd"), str):
            session.cwd = record["cwd"]
        # A name the person gave (/rename) wins over the newest title Claude Code generated.
        if record.get("type") == "custom-title" and isinstance(record.get("customTitle"), str):
            custom = record["customTitle"]
        elif record.get("type") == "ai-title" and isinstance(record.get("aiTitle"), str):
            ai = record["aiTitle"]
    session.title = custom or ai


def claude_session(path: Path) -> Session | None:
    if path.suffix != ".jsonl" or path.parent.parent != claude_root() / "projects":
        return None
    # Details are read only when the conversation is archived (see Session.load).
    return Session("claude", path.stem, path,
                   subagents=sorted((path.parent / path.stem / "subagents").glob("*.jsonl")),
                   details=claude_details)


def claude_sessions():
    for path in sorted((claude_root() / "projects").glob("*/*.jsonl")):
        session = claude_session(path)
        if session:
            yield session


# --- Codex: <home>/sessions/YYYY/MM/DD/rollout-*.jsonl (and archived_sessions/)

def codex_titles() -> dict[str, str]:
    """Thread names from session_index.jsonl; the newest entry for a thread wins."""
    titles = {}
    for record in all_records(codex_root() / "session_index.jsonl"):
        if isinstance(record.get("id"), str) and isinstance(record.get("thread_name"), str):
            titles[record["id"]] = record["thread_name"]
    return titles


def codex_session(path: Path, titles: dict[str, str] | None = None) -> Session | None:
    root = codex_root()
    if path.suffix != ".jsonl" or not any(path.is_relative_to(root / name) for name in ("sessions", "archived_sessions")):
        return None
    for record in head_records(path):
        if record.get("type") != "session_meta":
            continue
        meta = record.get("payload") or {}
        ident = meta.get("id") or meta.get("session_id")
        if not isinstance(ident, str) or not ident:
            return None
        source = meta.get("source")
        if isinstance(source, dict) and "subagent" in source:
            return None  # a subagent thread, not a conversation of its own
        titles = codex_titles() if titles is None else titles
        return Session("codex", ident, path, cwd=str(meta.get("cwd") or ""), title=titles.get(ident, ""))
    return None


def codex_sessions():
    titles = codex_titles()
    root = codex_root()
    for path in sorted({*root.glob("sessions/**/*.jsonl"), *root.glob("archived_sessions/**/*.jsonl")}):
        session = codex_session(path, titles)
        if session:
            yield session


# --- Antigravity: brain/<id>/.system_generated/logs/transcript_full.jsonl (or transcript.jsonl)

def agy_metadata() -> dict:
    try:
        value = json.loads((agy_root() / "cache/conversation_metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    conversations = value.get("conversations") if isinstance(value, dict) else None
    return conversations if isinstance(conversations, dict) else {}


def hints_file() -> Path:
    configured = os.environ.get("AGENT_HISTORY_DIR")
    return (Path(configured).expanduser() if configured else Path.home() / "agent-history") / "workspaces.json"


def workspace_hints() -> dict:
    """Working directories the Stop hooks reported, for conversations agy has not described yet."""
    try:
        value = json.loads(hints_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def remember_workspace(ident: str, cwd: str) -> None:
    hints = workspace_hints()
    if hints.get(ident) == cwd:
        return
    hints[ident] = cwd
    path = hints_file()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(hints, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(path)


def agy_workspace(ident: str) -> str:
    if workspace_hints().get(ident):
        return workspace_hints()[ident]
    try:  # agy's own record of the newest conversation in each folder
        latest = json.loads((agy_root() / "cache/last_conversations.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return next((folder for folder, conversation in latest.items() if conversation == ident), "") \
        if isinstance(latest, dict) else ""


def agy_session(path: Path, metadata: dict | None = None) -> Session | None:
    logs = path.parent
    if logs.name != "logs" or logs.parent.name != ".system_generated" or logs.parents[1].parent != agy_root() / "brain":
        return None
    ident = logs.parents[1].name
    transcript = logs / "transcript_full.jsonl"
    if not transcript.is_file():
        transcript = logs / "transcript.jsonl"
    if not transcript.is_file():
        return None
    for record in head_records(transcript):
        if record.get("type") == "USER_INPUT":
            if record.get("source") not in (None, "USER_EXPLICIT"):
                return None  # a subagent's task, not a conversation of its own
            break
    summary = ((metadata if metadata is not None else agy_metadata()).get(ident) or {}).get("summary") or {}
    workspaces = summary.get("WorkspaceURIs") or []
    cwd = workspaces[0].removeprefix("file://") if workspaces and isinstance(workspaces[0], str) else ""
    cwd = cwd or agy_workspace(ident)
    return Session("antigravity", ident, transcript, cwd=cwd, title=str(summary.get("Title") or ""))


def agy_sessions():
    metadata = agy_metadata()
    for logs in sorted((agy_root() / "brain").glob("*/.system_generated/logs")):
        session = agy_session(logs / "transcript.jsonl", metadata)
        if session:
            yield session


def all_sessions(providers=PROVIDERS):
    finders = {"claude": claude_sessions, "codex": codex_sessions, "antigravity": agy_sessions}
    for provider in providers:
        yield from finders[provider]()


def session_for(provider: str, transcript: str) -> Session | None:
    """The conversation a Stop hook's transcript path belongs to."""
    path = Path(transcript).expanduser()
    if provider == "claude":
        return claude_session(path)
    if provider == "codex":
        return codex_session(path)
    if provider == "antigravity":
        return agy_session(path)
    raise ValueError(f"unknown provider: {provider}")
