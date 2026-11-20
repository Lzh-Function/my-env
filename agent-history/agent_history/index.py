"""List, search, rename and export archived local conversations.

Reading never changes the archives: rename writes only titles.json next to the index,
and export-md writes only into the directory it is given (plus its state file there).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime
from functools import cached_property
from pathlib import Path

from .archive import history_root
from .obsidian_note import FORMAT, obsidian_body, zone

USER_TURN = re.compile(r"^### User · [^\n]*\n\n(.*?)(?=\n### |\n## |\n<details>|\Z)", re.MULTILINE | re.DOTALL)
MAIN_SESSION = re.compile(r"^## Session: .* \((worker|subagent), (?:codex|claude|antigravity)\)$", re.MULTILINE)
SECTION_END = re.compile(r"^## (?:Session: |Archive notes$)", re.MULTILINE)
TURN_TIME = re.compile(r"^### (?:User|Assistant) · (\S+)$", re.MULTILINE)
# Messages the CLIs add as "user" turns: system tags, AGENTS.md text, interruption notes.
ANY_TAG = re.compile(r"\s*(?:<[a-z][a-z_-]*>|# AGENTS\.md instructions|\[Request interrupted by user)")
COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# Built-in CLI commands that do not ask the agent for anything.
HOUSEKEEPING = {"exit", "quit", "clear", "model", "effort", "config", "status", "cost", "usage", "help",
                "login", "logout", "resume", "theme", "permissions", "statusline", "context", "mcp",
                "memory", "doctor", "vim", "terminal-setup", "privacy-settings", "release-notes", "rename"}
TITLES = "titles.json"
EXPORT_STATE = ".agent-history-export.json"
ARCHIVE_HEADER = re.compile(r"# Conversation archive\n\n(`{3,})json\n.*?\n\1\n", re.DOTALL)
# Characters Obsidian (and Windows/macOS sync) cannot keep in a file name or a [[link]].
UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
NAMES = {"claude": "claude", "codex": "codex", "antigravity": "antigravity"}


def safe_text(text):
    """Drop control characters so archived text cannot drive the terminal."""
    return "".join(c for c in str(text) if c == "\n" or not unicodedata.category(c).startswith("C"))


def spoken(text):
    """Whether a "user" turn is something the person actually asked."""
    text = text.strip()
    if not text:
        return False
    command = COMMAND.search(text) if text.startswith("<") else None
    if command:
        arguments = COMMAND_ARGS.search(text)
        return bool(arguments and arguments.group(1).strip()) or command.group(1) not in HOUSEKEEPING
    return not ANY_TAG.match(text)


def user_turns(markdown):
    """The person's turns in the main session (subagent tasks are written by the agent)."""
    for match in MAIN_SESSION.finditer(markdown):
        if match.group(1) != "worker":
            continue
        end = SECTION_END.search(markdown, match.end())
        section = markdown[match.end():end.start() if end else len(markdown)]
        yield from (turn.group(1) for turn in USER_TURN.finditer(section))


def readable(text):
    """A slash command as it was typed ("/goal finish the paper"), other text as it is."""
    command = COMMAND.search(text) if text.lstrip().startswith("<") else None
    if not command:
        return text.strip()
    arguments = COMMAND_ARGS.search(text)
    return f"/{command.group(1)} {arguments.group(1).strip() if arguments else ''}".strip()


def first_request(markdown):
    return next((readable(text) for text in user_turns(markdown) if spoken(text)), "")


def one_line(text, width):
    text = " ".join(safe_text(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def short_path(path):
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def snippets(markdown, words, limit=2, width=48):
    found, lower = [], markdown.lower()
    for word in words:
        start = 0
        while len(found) < limit:
            index = lower.find(word.lower(), start)
            if index < 0:
                break
            begin, end = max(0, index - width), min(len(markdown), index + len(word) + width)
            found.append(("…" if begin else "") + " ".join(markdown[begin:end].split())
                         + ("…" if end < len(markdown) else ""))
            start = index + len(word)
    return found[:limit]


def load_titles():
    try:
        value = json.loads((history_root() / TITLES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def parse_time(stamp):
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return moment.astimezone(zone()) if moment.tzinfo else None


class Conversation:
    def __init__(self, row):
        self.row = row
        self.metadata = json.loads(row["metadata_json"])

    @property
    def key(self):
        return self.row["archive_id"]

    @property
    def markdown(self):
        return self.row["markdown"]

    @cached_property
    def _times(self):
        moments = [m for m in map(parse_time, TURN_TIME.findall(self.markdown)) if m]
        return (min(moments), max(moments)) if moments else (None, None)

    def times(self):
        return self._times

    @property
    def started(self):
        return self.times()[0]

    @property
    def last_active(self):
        return self.times()[1]

    @property
    def noise(self):
        """Opened and closed without asking anything."""
        return not any(spoken(text) for text in user_turns(self.markdown))

    def label(self, titles=None):
        renamed = (titles if titles is not None else load_titles()).get(self.key, {})
        return renamed.get("title") or self.row["title"]


def connect():
    database = history_root() / "index.sqlite3"
    if not database.is_file():
        return None
    db = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def conversations(db, words=(), provider=None, project="", noise=False):
    """Matching conversations, most recently active first; noise=True returns the hidden ones."""
    query, params = "SELECT * FROM conversations WHERE 1=1", []
    if provider:
        query += " AND provider = ?"
        params.append(provider)
    if project:
        query += " AND instr(cwd, ?) > 0"
        params.append(project)
    found = [c for c in map(Conversation, db.execute(query, params))
             if c.noise == noise and all(w.lower() in c.markdown.lower() for w in words)]
    epoch = datetime.fromtimestamp(0, zone())
    return sorted(found, key=lambda c: (c.last_active or epoch, c.key), reverse=True)


def show(found, words, limit):
    if not found:
        print("該当する会話はありません。" if words else "保存された会話はまだありません。")
        return
    titles = load_titles()
    for conversation in found[:limit]:
        row = conversation.row
        started = conversation.started.strftime("%Y-%m-%d %H:%M") if conversation.started else "不明"
        heading = "  ".join(part for part in (started, row["provider"], Path(row["cwd"]).name or row["cwd"],
                                               one_line(conversation.label(titles), 50)) if part)
        print(safe_text(heading))
        last = conversation.last_active.strftime("%Y-%m-%d %H:%M") if conversation.last_active else "不明"
        print(f"    最終更新: {last}")
        request = first_request(conversation.markdown)
        if request:
            print("    最初の依頼: " + one_line(request, 70))
        for text in snippets(conversation.markdown, words):
            print("    一致: " + one_line(text, 110))
        print("    ID: " + row["session_id"] + "    " + safe_text(short_path(row["markdown_path"])))
    if len(found) > limit:
        print(f"（ほかに {len(found) - limit} 件。--limit で増やせます）")


def note_name(conversation, label):
    started = conversation.started
    prefix = started.strftime("%Y-%m-%d %H%M") if started else conversation.row["session_id"][:8]
    label = " ".join(UNSAFE_NAME.sub(" ", safe_text(label)).split()).strip(" .")
    if len(label) > 60:
        label = label[:59].rstrip() + "…"
    return f"{prefix} {label}".strip()


def frontmatter(conversation, label):
    row = conversation.row
    fields = {
        "date": conversation.started.strftime("%Y-%m-%dT%H:%M:%S") if conversation.started else None,
        "last_active": conversation.last_active.strftime("%Y-%m-%dT%H:%M:%S") if conversation.last_active else None,
        "agent": row["provider"], "project": row["cwd"], "title": label, "session_id": row["session_id"],
        "archived_at": row["updated_at"],
    }
    # JSON values are valid YAML flow scalars and sequences, so any text is safe here.
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items() if value]
    return "---\n" + "\n".join(lines) + "\ntags: [agent-history]\n---\n"


def write_private(path, text):
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


def export_markdown(found, directory, hidden=()):
    """Write one Obsidian note per conversation; touch only notes this command wrote."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / EXPORT_STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    dropped = 0
    for conversation in hidden:
        entry = state.pop(conversation.key, None)
        if entry:
            (directory / entry["file"]).unlink(missing_ok=True)
            dropped += 1
    titles = load_titles()
    taken = {entry["file"] for entry in state.values()}
    counts = {"new": 0, "updated": 0, "same": 0}
    tz = zone()
    for conversation in reversed(found):
        label = conversation.label(titles) or one_line(first_request(conversation.markdown), 60) \
            or conversation.row["provider"]
        name = note_name(conversation, label) + ".md"
        previous = state.get(conversation.key)
        if previous and re.fullmatch(re.escape(name[:-3]) + r" \(\d+\)\.md", previous["file"]):
            name = previous["file"]  # keeps the suffix it got for a name clash earlier
        version = {"updated_at": conversation.row["updated_at"], "format": FORMAT}
        if previous and previous["file"] == name and all(previous.get(k) == v for k, v in version.items()) \
                and (directory / name).is_file():
            counts["same"] += 1
            continue
        if not previous or previous["file"] != name:
            # Never overwrite a note this command did not write.
            stem, number = name[:-3], 2
            while name in taken or ((directory / name).exists() and not (previous and previous["file"] == name)):
                name, number = f"{stem} ({number}).md", number + 1
        header = ARCHIVE_HEADER.match(conversation.markdown)
        if not header:
            raise ValueError(f"unexpected archive layout: {conversation.key}")
        write_private(directory / name, frontmatter(conversation, label) + "\n"
                      + obsidian_body(conversation.markdown[header.end():], tz))
        if previous and previous["file"] != name:
            (directory / previous["file"]).unlink(missing_ok=True)  # the title changed
            taken.discard(previous["file"])
        taken.add(name)
        state[conversation.key] = {"file": name, **version}
        counts["updated" if previous else "new"] += 1
    write_private(state_path, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    note = f"、依頼のない会話のノートを {dropped} 件削除しました" if dropped else ""
    print(f"書き出しました: 新規 {counts['new']} 件、更新 {counts['updated']} 件、"
          f"変更なし {counts['same']} 件{note} → {directory}")


def find_conversation(found, ident):
    exact = [c for c in found if c.row["session_id"] == ident]
    matches = exact or [c for c in found if c.row["session_id"].startswith(ident)]
    if not matches:
        raise ValueError(f"{ident} に当たる会話がありません。ID は agent-history list の「ID:」で確かめられます")
    if len(matches) > 1:
        raise ValueError(f"{ident} に当たる会話が {len(matches)} 件あります。もっと長く指定してください: "
                         + ", ".join(c.row["session_id"] for c in matches[:5]))
    return matches[0]


def rename(found, ident, name, clear):
    conversation = find_conversation(found, ident)
    name = " ".join(safe_text(name).split())
    if not clear and not name:
        raise ValueError("新しい名前を指定してください（元に戻すときは --clear）")
    if len(name) > 200:
        raise ValueError("名前は 200 文字までにしてください")
    titles = load_titles()
    before = conversation.label(titles)
    if clear:
        titles.pop(conversation.key, None)
    else:
        titles[conversation.key] = {"title": name, "session_id": conversation.row["session_id"],
                                    "renamed_at": time.time()}
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(root / TITLES, json.dumps(titles, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"名前を変えました: {before or '（名前なし）'} → {conversation.label(titles) or '（名前なし）'}")
    print("書き出したノートの名前は、次に export-md を実行したときに変わります。")
