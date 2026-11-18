#!/usr/bin/env python3
"""List, search, rename and export archived conversations from the shared history database.

The database is opened read-only. export-md only writes into the directory it is given, and
rename only writes the separate titles file next to the database; archives stay as they are.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

from history_export import archive_key, history_root
from obsidian_note import FORMAT, obsidian_body, zone
from sessions import safe_text

RUN_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
USER_TURN = re.compile(r"^### User · [^\n]*\n\n(.*?)(?=\n### |\n## |\n<details>|\Z)", re.MULTILINE | re.DOTALL)
WORKER_SESSION = re.compile(r"^## Session: .* \((worker|reviewer), (?:codex|claude)\)$", re.MULTILINE)
SECTION_END = re.compile(r"^## (?:Session: |Review: |Archive notes$)", re.MULTILINE)
# The prompt agentrun itself sends to start an interactive assist session; batch prompts carry a goal.
CAPSULE_PROMPT = "You are running inside an HPC agent capsule."
INTERACTIVE_PROMPT = "Wait for the user's first instruction."
ANY_TAG = re.compile(r"\s*(?:<[a-z][a-z_-]*>|# AGENTS\.md instructions|\[Request interrupted by user)")
COMMAND = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# Built-in CLI commands that do not ask the agent for anything.
HOUSEKEEPING = {"exit", "quit", "clear", "model", "effort", "config", "status", "cost", "usage", "help",
                "login", "logout", "resume", "theme", "permissions", "statusline", "context", "mcp",
                "memory", "doctor", "vim", "terminal-setup", "privacy-settings", "release-notes"}
TITLES = "titles.json"


def spoken(text):
    """Whether a worker "user" turn is something the person actually asked."""
    text = text.strip()
    if not text or (text.startswith(CAPSULE_PROMPT) and INTERACTIVE_PROMPT in text):
        return False
    command = COMMAND.search(text) if text.startswith("<") else None
    if command:
        arguments = COMMAND_ARGS.search(text)
        return bool(arguments and arguments.group(1).strip()) or command.group(1) not in HOUSEKEEPING
    return not ANY_TAG.match(text)


def worker_turns(markdown):
    for match in WORKER_SESSION.finditer(markdown):
        if match.group(1) != "worker":
            continue
        end = SECTION_END.search(markdown, match.end())
        section = markdown[match.end():end.start() if end else len(markdown)]
        yield from (turn.group(1) for turn in USER_TURN.finditer(section))


def load_titles():
    try:
        value = json.loads((history_root() / TITLES).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def connect():
    database = history_root() / "index.sqlite3"
    if not database.is_file():
        return None
    return sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=30)


def started(run_id):
    match = RUN_TIME.match(run_id)
    return "{}-{}-{} {}:{}".format(*match.groups()[:5]) if match else run_id


def title(run_parent, run_id, metadata):
    """The ~5-word run title the agent wrote, from the archive or the run directory."""
    if metadata.get("title"):
        return metadata["title"]
    for run in sorted(Path(run_parent).glob(glob_escape(run_id) + "*")):
        try:
            return (run / "artifacts/run_title.txt").read_text(encoding="utf-8").strip().splitlines()[0]
        except (OSError, IndexError, UnicodeError):
            continue
    return ""


def glob_escape(text):
    return re.sub(r"([*?\[])", r"[\1]", text)


GOAL = re.compile(r"\nUser goal:\n(.*?)(?:\n\nRequired outputs|\Z)", re.DOTALL)


def first_request(markdown):
    """What the person first asked: their first own message, or the goal of a batch prompt."""
    for text in worker_turns(markdown):
        if not spoken(text):
            continue
        text = text.strip()
        if text.removeprefix("/goal ").startswith(CAPSULE_PROMPT):
            goal = GOAL.search(text)
            if goal and goal.group(1).strip():
                return goal.group(1).strip()
            continue
        return text
    return ""


def one_line(text, width):
    text = " ".join(safe_text(text).split())
    return text if len(text) <= width else text[:width - 1] + "…"


def short_path(path):
    home = str(Path.home())
    return "~" + path[len(home):] if path == home or path.startswith(home + "/") else path


def snippets(markdown, words, limit=2, width=48):
    """Text around the first matches of the search words, in file order."""
    found = []
    lower = markdown.lower()
    for word in words:
        start = 0
        while len(found) < limit:
            index = lower.find(word.lower(), start)
            if index < 0:
                break
            begin, end = max(0, index - width), min(len(markdown), index + len(word) + width)
            found.append(("…" if begin else "") + " ".join(markdown[begin:end].split()) + ("…" if end < len(markdown) else ""))
            start = index + len(word)
    return found[:limit]


class Conversation:
    """All archived runs of one conversation: the original run and every resume of it.

    Resumed runs share the original run's session store, so the newest run's archive holds
    the whole conversation; the older archives are earlier, shorter copies of it.
    """

    def __init__(self, runs):
        self.runs = sorted(runs, key=lambda row: row["run_id"])
        self.first, self.latest = self.runs[0], self.runs[-1]
        self.metadata = json.loads(self.latest["metadata_json"])

    @property
    def key(self):
        # Equals the original run's archive ID, so notes exported before grouping keep their entry.
        return archive_key(Path(self.latest["run_parent"]), self.latest["session_key"])

    @property
    def resumes(self):
        return len(self.runs) - 1

    @property
    def noise(self):
        """No one ever asked anything: only agentrun's own interactive start prompt (or nothing)."""
        return not any(spoken(text) for row in self.runs for text in worker_turns(row["markdown"]))

    def label(self, titles=None):
        """The name given with `history rename`, else the newest title any of its runs wrote."""
        renamed = (titles if titles is not None else load_titles()).get(self.key, {})
        if renamed.get("title"):
            return renamed["title"]
        for row in reversed(self.runs):
            text = title(row["run_parent"], row["run_id"], json.loads(row["metadata_json"]))
            if text:
                return text
        return ""

    def contains(self, words):
        return all(any(word.lower() in row["markdown"].lower() for row in self.runs) for word in words)


def conversations(db, words, agent, repo, noise=False):
    """Matching conversations, most recently used first; noise=True returns only the hidden ones."""
    query = ("SELECT archive_id, run_id, run_parent, agent, repo, session_key, markdown_path, metadata_json, "
             "markdown, updated_at FROM conversations WHERE 1=1")
    params = []
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if repo:
        query += " AND instr(repo, ?) > 0"
        params.append(repo)
    db.row_factory = sqlite3.Row
    groups = {}
    for row in db.execute(query, params):
        groups.setdefault((row["run_parent"], row["session_key"]), []).append(row)
    found = [conversation for conversation in map(Conversation, groups.values())
             if conversation.noise == noise and conversation.contains(words)]
    # Run IDs start with the launch time: most recently used conversation first.
    return sorted(found, key=lambda c: (c.latest["run_id"], c.latest["archive_id"]), reverse=True)


def show(found, words, limit):
    if not found:
        print("該当する会話はありません。" if words else "保存された会話はまだありません。")
        return
    titles = load_titles()
    for conversation in found[:limit]:
        latest = conversation.latest
        heading = "  ".join(part for part in (
            started(conversation.first["run_id"]), latest["agent"], conversation.metadata.get("mode", ""),
            Path(latest["repo"]).name or latest["repo"], one_line(conversation.label(titles), 50)) if part)
        print(safe_text(heading))
        if conversation.resumes:
            print(f"    resume {conversation.resumes} 回・最終 {started(latest['run_id'])}")
        request = first_request(latest["markdown"])
        if request:
            print("    最初の依頼: " + one_line(request, 70))
        for text in snippets(latest["markdown"], words):
            print("    一致: " + one_line(text, 110))
        print("    ID: " + conversation.first["run_id"] + "    " + safe_text(short_path(latest["markdown_path"])))
    if len(found) > limit:
        print(f"（ほかに {len(found) - limit} 件。--limit で増やせます）")


# Characters Obsidian (and Windows/macOS sync) cannot keep in a file name or a [[link]].
UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
EXPORT_STATE = ".agentrun-export.json"
ARCHIVE_HEADER = re.compile(r"# Conversation archive\n\n(`{3,})json\n.*?\n\1\n", re.DOTALL)


def note_name(run_id, label):
    stamp = RUN_TIME.match(run_id)
    prefix = "{}-{}-{} {}{}".format(*stamp.groups()[:5]) if stamp else run_id
    label = " ".join(UNSAFE_NAME.sub(" ", safe_text(label)).split()).strip(" .")
    if len(label) > 60:
        label = label[:59].rstrip() + "…"
    return f"{prefix} {label}".strip()


def iso_time(run_id):
    stamp = RUN_TIME.match(run_id)
    return "{}-{}-{}T{}:{}:{}".format(*stamp.groups()) if stamp else None


def frontmatter(conversation, label):
    first, latest = conversation.first, conversation.latest
    fields = {
        "date": iso_time(first["run_id"]),
        "last_active": iso_time(latest["run_id"]) if conversation.resumes else None,
        "agent": latest["agent"], "mode": conversation.metadata.get("mode"), "repo": latest["repo"],
        "title": label, "run_id": first["run_id"],
        "runs": [row["run_id"] for row in conversation.runs] if conversation.resumes else None,
        "resumes": conversation.resumes or None,
        "archive_id": latest["archive_id"], "archived_at": latest["updated_at"],
    }
    # JSON values are valid YAML flow scalars and sequences, so any text is safe here.
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items() if value]
    return "---\n" + "\n".join(lines) + "\ntags: [agentrun]\n---\n"


def write_private(path, text):
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


def export_markdown(found, directory, hidden=()):
    """Write one Obsidian-friendly note per conversation; touch only notes this command wrote."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / EXPORT_STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    # Earlier exports wrote one note per resumed run; those notes now belong to their conversation.
    merged = 0
    for conversation in found:
        for row in conversation.runs:
            entry = state.get(row["archive_id"]) if row["archive_id"] != conversation.key else None
            if entry:
                (directory / entry["file"]).unlink(missing_ok=True)
                del state[row["archive_id"]]
                merged += 1
    # Notes this command wrote earlier for conversations that turned out to be empty starts.
    dropped = 0
    for conversation in hidden:
        for ident in {conversation.key, *(row["archive_id"] for row in conversation.runs)}:
            entry = state.pop(ident, None)
            if entry:
                (directory / entry["file"]).unlink(missing_ok=True)
                dropped += 1
    titles = load_titles()
    taken = {entry["file"] for entry in state.values()}
    counts = {"new": 0, "updated": 0, "same": 0}
    tz = zone()
    for conversation in reversed(found):
        latest = conversation.latest
        label = conversation.label(titles) or one_line(first_request(latest["markdown"]), 60) or latest["agent"]
        name = note_name(conversation.first["run_id"], label) + ".md"
        previous = state.get(conversation.key)
        if previous and re.fullmatch(re.escape(name[:-3]) + r" \(\d+\)\.md", previous["file"]):
            name = previous["file"]  # keeps the suffix it got for a name clash earlier
        version = {"updated_at": latest["updated_at"], "source": latest["archive_id"], "format": FORMAT}
        if previous and previous["file"] == name and all(previous.get(k) == v for k, v in version.items()) \
                and (directory / name).is_file():
            counts["same"] += 1
            continue
        if not previous or previous["file"] != name:
            # Never overwrite a note this command did not write (the user's own, or another run's).
            stem, number = name[:-3], 2
            while name in taken or ((directory / name).exists() and not (previous and previous["file"] == name)):
                name, number = f"{stem} ({number}).md", number + 1
        header = ARCHIVE_HEADER.match(latest["markdown"])
        if not header:
            raise ValueError(f"unexpected archive layout: {latest['archive_id']}")
        write_private(directory / name, frontmatter(conversation, label)
                      + "\n" + obsidian_body(latest["markdown"][header.end():], tz))
        if previous and previous["file"] != name:
            (directory / previous["file"]).unlink(missing_ok=True)  # the title changed
            taken.discard(previous["file"])
        taken.add(name)
        state[conversation.key] = {"file": name, **version}
        counts["updated" if previous else "new"] += 1
    write_private(state_path, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    note = f"、resume 前の重複ノートを {merged} 件まとめました" if merged else ""
    note += f"、依頼のない会話のノートを {dropped} 件削除しました" if dropped else ""
    print(f"書き出しました: 新規 {counts['new']} 件、更新 {counts['updated']} 件、変更なし {counts['same']} 件{note} → {directory}")


def find_conversation(found, ident):
    """The conversation one of whose runs has this run ID (or the only one starting with it)."""
    exact = [c for c in found if any(row["run_id"] == ident for row in c.runs)]
    matches = exact or [c for c in found if any(row["run_id"].startswith(ident) for row in c.runs)]
    if not matches:
        raise ValueError(f"{ident} に当たる会話がありません。ID は history list の「ID:」で確かめられます")
    if len(matches) > 1:
        raise ValueError(f"{ident} に当たる会話が {len(matches)} 件あります。もっと長く指定してください: "
                         + ", ".join(c.first["run_id"] for c in matches[:5]))
    return matches[0]


def rename(found, ident, name, clear):
    conversation = find_conversation(found, ident)
    name = " ".join(safe_text(name).split())
    if not clear and not name:
        raise ValueError("新しい名前を指定してください（元に戻すときは --clear）")
    if len(name) > 200:
        raise ValueError("名前は 200 文字までにしてください")
    root = history_root()
    titles = load_titles()
    before = conversation.label(titles)
    if clear:
        titles.pop(conversation.key, None)
    else:
        titles[conversation.key] = {"title": name, "run_id": conversation.first["run_id"], "renamed_at": time.time()}
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(root / TITLES, json.dumps(titles, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    after = conversation.label(titles)
    print(f"名前を変えました: {before or '（名前なし）'} → {after or '（名前なし）'}")
    print("書き出したノートの名前は、次に export-md を実行したときに変わります。")


def choices(found, limit):
    """Tab-separated run ID and label lines for the wizard's picker."""
    titles = load_titles()
    for conversation in found[:limit]:
        current = one_line(conversation.label(titles), 200)
        label = current or one_line(first_request(conversation.latest["markdown"]), 40) or "（名前なし）"
        resumed = f"（resume {conversation.resumes} 回）" if conversation.resumes else ""
        print(f"{conversation.first['run_id']}\t{started(conversation.first['run_id'])}  "
              f"{Path(conversation.latest['repo']).name}  {one_line(label, 50)}{resumed}\t{current}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "search", "export-md", "rename", "choices"))
    parser.add_argument("words", nargs="*",
                        help="search words, the target directory for export-md, or RUN_ID NEW NAME for rename")
    parser.add_argument("--clear", action="store_true", help="rename: go back to the title the agent wrote")
    parser.add_argument("--agent", choices=("claude", "codex"))
    parser.add_argument("--repo", default="", help="only conversations whose repository path contains this text")
    parser.add_argument("--limit", type=int, default=20)
    options = parser.parse_args()
    if options.action == "list" and options.words:
        parser.error("list takes no words; use search")
    if options.action == "search" and not options.words:
        parser.error("search needs at least one word")
    if options.action == "export-md" and len(options.words) != 1:
        parser.error("export-md needs exactly one target directory")
    if options.action == "rename" and (not options.words or (options.clear and len(options.words) != 1)):
        parser.error("usage: history rename RUN_ID NEW NAME  (or: history rename RUN_ID --clear)")
    if options.limit < 1:
        parser.error("--limit must be positive")
    db = connect()
    if db is None:
        if options.action == "rename":
            raise ValueError("保存された会話はまだありません（" + str(history_root()) + "）")
        if options.action != "choices":  # the wizard reads choices as data: print nothing
            print("保存された会話はまだありません（" + str(history_root()) + "）。")
        return 0
    words = options.words if options.action == "search" else []
    try:
        found = conversations(db, words, options.agent, options.repo)
        hidden = conversations(db, [], options.agent, options.repo, noise=True) if options.action == "export-md" else []
    finally:
        db.close()
    if options.action == "export-md":
        export_markdown(found, Path(options.words[0]).expanduser().resolve(), hidden)
    elif options.action == "rename":
        rename(found, options.words[0], " ".join(options.words[1:]), options.clear)
    elif options.action == "choices":
        choices(found, options.limit)
    else:
        show(found, words, options.limit)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error) as error:
        print("history: " + str(error), file=sys.stderr)
        sys.exit(2)
