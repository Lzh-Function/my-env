#!/usr/bin/env python3
"""List, search, rename and export archived conversations from the shared history database.

The database is opened read-only. export-md only writes into the directory it is given, and
rename only writes the separate titles file next to the database; archives stay as they are.
The one exception is export-md --live, which first saves running sessions as `agentrun history
RUN` would (the end-of-session save later replaces that snapshot with the full conversation).
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from history_export import SECTION_HEAD, archive_key, chronological, history_root
from obsidian_note import FORMAT, GUIDE, obsidian_body, zone
from sessions import safe_text

RUN_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
USER_TURN = re.compile(r"^### User · [^\n]*\n\n(.*?)(?=\n### |\n## |\n<details>|\Z)", re.MULTILINE | re.DOTALL)
WORKER_SESSION = re.compile(r"^## Session: .* \((worker|reviewer), (?:codex|claude|antigravity)\)$", re.MULTILINE)
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
TURN_TIME = re.compile(r"^### (?:User|Assistant) · (\S+)$", re.MULTILINE)


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


SESSION_LINE = re.compile(r"## Session: (.*) \((worker|reviewer), (codex|claude|antigravity)\)\n")
FIRST_FENCE = re.compile(r"\n(`{3,})json\n(.*?)\n\1\n", re.DOTALL)


def moment(stamp):
    try:
        value = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None


def log_time(text):
    """A session log time ("2026-11-20 16:40", AGENTRUN_TIMEZONE) as an aware datetime, or None."""
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=zone()) if text else None
    except ValueError:
        return None


def first_time(text):
    times = [m for m in map(moment, TURN_TIME.findall(text)) if m]
    return min(times) if times else None


def section_metadata(text):
    found = FIRST_FENCE.search(text)
    try:
        value = json.loads(found.group(2)) if found else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def subagent_parent(provider, metadata):
    """None for a session the person talks to; else the ID of the conversation that started it ("" if unknown)."""
    if provider == "claude":
        file = str(metadata.get("file", ""))
        if "/subagents/" in file:
            return Path(file).parent.parent.name
        return "" if metadata.get("isSidechain") is True else None
    if provider == "codex":
        source = metadata.get("source")
        if metadata.get("parent_thread_id") or (isinstance(source, dict) and "subagent" in source):
            return str(metadata.get("parent_thread_id") or "")
        return None
    return "" if metadata.get("started_by") else None


CLEARED = re.compile(r"<command-name>/(?:clear|new)</command-name>")


def sections_of(markdown):
    heads = [m.start() for m in SECTION_HEAD.finditer(markdown)]
    if not heads:
        return markdown, []
    return markdown[:heads[0]], [markdown[start:(heads[i + 1] if i + 1 < len(heads) else len(markdown))]
                                 for i, start in enumerate(heads)]


def main_sessions(markdown):
    """[(start time, conversation ID, provider, began with /clear)] of the sessions the person talked in."""
    found = []
    for text in sections_of(markdown)[1]:
        line = SESSION_LINE.match(text)
        if not line or line.group(2) != "worker":
            continue
        metadata = section_metadata(text)
        if subagent_parent(line.group(3), metadata) is not None:
            continue
        ident = str(metadata.get("sessionId") or metadata.get("id") or metadata.get("conversation_id") or line.group(1))
        turns = [turn.group(1) for turn in USER_TURN.finditer(text)][:3]
        found.append((first_time(text), ident, line.group(3), any(CLEARED.search(turn) for turn in turns)))
    never = datetime.max.replace(tzinfo=timezone.utc)
    return sorted(found, key=lambda item: item[0] or never)


def conversation_groups(markdown):
    """The sessions of a run (and its resumes) grouped into conversations, oldest first.

    /clear starts a new native session. Claude Code marks it: the new session begins with the
    /clear command; older Claude Code also wrote a new session file on resume or compaction,
    which continues the same conversation. Codex and Antigravity keep one session across resume
    and compaction, so each new one of theirs (not a subagent) is a new conversation.
    """
    groups = []
    for _, ident, provider, cleared in main_sessions(markdown):
        if groups and provider == "claude" and not cleared:
            groups[-1].append(ident)
        else:
            groups.append([ident])
    return groups


def split_conversations(markdown, groups):
    """{conversation ID: its part of this archive} for the conversations of `groups` it holds.

    Subagents go with the conversation that started them; reviewer sessions and reviews with the
    conversation going on at the time (the one whose session started last before them).
    """
    header, sections = sections_of(markdown)
    owner_of = {ident: group[0] for group in groups for ident in group}
    starts, owners, reviewer_times = [], [None] * len(sections), {}
    for index, text in enumerate(sections):
        line = SESSION_LINE.match(text)
        if not line:
            continue
        metadata = section_metadata(text)
        if line.group(2) == "reviewer":
            for key in ("sessionId", "id", "session_id", "conversation_id"):
                if metadata.get(key):
                    reviewer_times[str(metadata[key])] = first_time(text)
            continue
        parent = subagent_parent(line.group(3), metadata)
        ident = str(metadata.get("sessionId") or metadata.get("id") or metadata.get("conversation_id") or line.group(1))
        if parent is None and ident in owner_of:
            owners[index] = owner_of[ident]
            starts.append((first_time(text), owner_of[ident]))
        elif parent and parent in owner_of:
            owners[index] = owner_of[parent]
    present = list(dict.fromkeys(owner for _, owner in starts))
    if len(present) < 2:
        return {present[0]: markdown} if present else {}
    never = datetime.max.replace(tzinfo=timezone.utc)
    starts.sort(key=lambda item: item[0] or never)

    def active_at(when):
        current = starts[0][1]
        if when is None:
            return starts[-1][1]
        for start, owner in starts:
            if start is not None and start <= when:
                current = owner
        return current

    parts = {owner: [] for owner in present}
    for index, text in enumerate(sections):
        owner = owners[index]
        if owner is None:
            if text.startswith("## Archive notes"):
                for part in parts.values():
                    part.append(text)
                continue
            when = first_time(text)
            if text.startswith("## Review: "):
                when = reviewer_times.get(str(section_metadata(text).get("session_id")))
            owner = active_at(when)
        parts[owner].append(text)
    return {owner: header + "".join(texts) for owner, texts in parts.items()}


class Conversation:
    """All archived runs of one conversation: the original run and every resume of it.

    Resumed runs share the original run's session store, so the newest run's archive holds
    the whole conversation; the older archives are earlier, shorter copies of it.
    """

    def __init__(self, runs, part=None):
        self.runs = sorted(runs, key=lambda row: row["run_id"])
        self.first, self.latest = self.runs[0], self.runs[-1]
        self.metadata = json.loads(self.latest["metadata_json"])
        # Set on the conversations split from one run by /clear: (number, conversation ID, count).
        self.part = part
        # The time span of a conversation split by /clear, for its session log lines: (from, until).
        self.window = (None, None)

    @property
    def key(self):
        # Equals the original run's archive ID, so notes exported before grouping keep their entry.
        # The first conversation of a run keeps it; later ones (after /clear) add their own ID.
        key = archive_key(Path(self.latest["run_parent"]), self.latest["session_key"])
        return key if not self.part or self.part[0] == 1 else f"{key}~{self.part[1]}"

    @property
    def ident(self):
        """What `history list` shows as the ID: the first run ID, plus ~N for the Nth conversation after /clear."""
        return self.first["run_id"] if not self.part or self.part[0] == 1 else f"{self.first['run_id']}~{self.part[0]}"

    @property
    def begin(self):
        """When a conversation started after /clear began (None: it starts with its first run)."""
        if not self.part or self.part[0] == 1:
            return None
        when = first_time(self.first["markdown"])
        return when.astimezone(zone()) if when else None

    def split(self):
        """One Conversation per conversation the person had: /clear starts a new one."""
        groups = conversation_groups(self.latest["markdown"])
        if len(groups) < 2:
            return [self]
        found = []
        for number, group in enumerate(groups, 1):
            rows, previous = [], None
            for row in self.runs:
                text = split_conversations(row["markdown"], groups).get(group[0])
                # A run belongs to this conversation when it added to it (resume, or the run of /clear).
                if text is not None and text != previous:
                    rows.append({**row, "markdown": text})
                    previous = text
            if rows:
                found.append(Conversation(rows, (number, group[0], len(groups))))
        # Session log lines go by their time: from a conversation's start (to the minute, as the
        # lines are written) until the next one starts.
        starts = [None if c.begin is None else c.begin.replace(second=0, microsecond=0) for c in found]
        for index, conversation in enumerate(found):
            conversation.window = (starts[index], starts[index + 1] if index + 1 < len(found) else None)
        return found

    @property
    def session_log(self):
        """The agent's one-line summaries of its turns, oldest first: [(time or None, text)]."""
        if not hasattr(self, "_session_log"):
            lines, seen = [], set()
            for row in self.runs:
                for line in json.loads(row["metadata_json"]).get("session_log") or []:
                    item = (line.get("time"), str(line.get("text") or "").strip())
                    if item[1] and item not in seen:
                        seen.add(item)
                        lines.append(item)
            start, end = self.window
            kept = []
            for when, text in lines:
                when_ = log_time(when)
                if when_ and ((start and when_ < start) or (end and when_ >= end)):
                    continue
                kept.append((when, text))
            # Resumed runs each keep their own log: put the lines in time order. A line without a time
            # cannot be placed, so then the runs' order (oldest run first) is kept as it is.
            if all(when for when, _ in kept):
                kept.sort(key=lambda item: item[0])
            self._session_log = kept
        return self._session_log

    @property
    def session_log_text(self):
        return "\n".join(f"- {when} {text}" if when else f"- {text}" for when, text in self.session_log)

    @property
    def resumes(self):
        return len(self.runs) - 1

    @property
    def last_active(self):
        """When the conversation last moved: its newest message, else when its newest run started."""
        if not hasattr(self, "_last_active"):
            newest = None
            for stamp in TURN_TIME.findall(self.latest["markdown"]):
                try:
                    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if moment.tzinfo is not None and (newest is None or moment > newest):
                    newest = moment
            if newest is None:
                stamp = RUN_TIME.match(self.latest["run_id"])
                # Run IDs are the launch host's clock; show them as they are, like the start time.
                newest = datetime(*map(int, stamp.groups()), tzinfo=zone()) if stamp else None
            self._last_active = newest.astimezone(zone()) if newest else None
        return self._last_active

    @property
    def noise(self):
        """No one ever asked anything: only agentrun's own interactive start prompt (or nothing)."""
        return not any(spoken(text) for row in self.runs for text in worker_turns(row["markdown"]))

    def label(self, titles=None):
        """The name given with `history rename`, else the newest title any of its runs wrote."""
        renamed = (titles if titles is not None else load_titles()).get(self.key, {})
        if renamed.get("title"):
            return renamed["title"]
        if self.part and self.part[0] != self.part[2]:
            return ""  # a run's title describes where it ended: the last conversation of the run
        for row in reversed(self.runs):
            text = title(row["run_parent"], row["run_id"], json.loads(row["metadata_json"]))
            if text:
                return text
        return ""

    def contains(self, words):
        log = self.session_log_text.lower()
        return all(word.lower() in log or any(word.lower() in row["markdown"].lower() for row in self.runs)
                   for word in words)


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
        # Archives saved before sessions were put in time order are reordered as they are read.
        row = {**dict(row), "markdown": chronological(row["markdown"])}
        groups.setdefault((row["run_parent"], row["session_key"]), []).append(row)
    found = [conversation for group in groups.values() for conversation in Conversation(group).split()
             if conversation.noise == noise and conversation.contains(words)]
    # Run IDs start with the launch time: most recently used conversation first.
    # Most recently active first; run IDs (launch times) break ties and cover missing times.
    return sorted(found, key=lambda c: (c.last_active.timestamp() if c.last_active else 0,
                                        c.latest["run_id"], c.latest["archive_id"]), reverse=True)


def show(found, words, limit):
    from history_schedule import failure_notice
    notice = failure_notice()
    if notice:
        print(notice + "\n")
    if not found:
        print("該当する会話はありません。" if words else "保存された会話はまだありません。")
        return
    titles = load_titles()
    for conversation in found[:limit]:
        latest = conversation.latest
        heading = "  ".join(part for part in (
            f"{conversation.begin:%Y-%m-%d %H:%M}" if conversation.begin else started(conversation.first["run_id"]),
            latest["agent"], conversation.metadata.get("mode", ""),
            Path(latest["repo"]).name or latest["repo"], one_line(conversation.label(titles), 50)) if part)
        print(safe_text(heading))
        when = conversation.last_active.strftime("%Y-%m-%d %H:%M") if conversation.last_active else "不明"
        resumed = f"（resume {conversation.resumes} 回）" if conversation.resumes else ""
        print(f"    最終更新: {when}{resumed}")
        request = first_request(latest["markdown"])
        if request:
            print("    最初の依頼: " + one_line(request, 70))
        if conversation.session_log:
            when, text = conversation.session_log[-1]
            print("    最後の作業: " + one_line(f"{when} {text}" if when else text, 70))
        # Matching session log lines first (they say what was done), then the conversation around the words.
        logged = [line for line in conversation.session_log_text.splitlines()
                  if words and any(word.lower() in line.lower() for word in words)][:2]
        for text in logged + snippets(latest["markdown"], words)[:2 - len(logged)]:
            print("    一致: " + one_line(text, 110))
        cleared = f"（/clear 後の {conversation.part[0]} つ目の会話）" if conversation.part and conversation.part[0] > 1 else ""
        print("    ID: " + conversation.ident + "    " + safe_text(short_path(latest["markdown_path"])) + cleared)
    if len(found) > limit:
        print(f"（ほかに {len(found) - limit} 件。--limit で増やせます）")


# Characters Obsidian (and Windows/macOS sync) cannot keep in a file name or a [[link]].
UNSAFE_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
EXPORT_STATE = ".agentrun-export.json"
ARCHIVE_HEADER = re.compile(r"# Conversation archive\n\n(`{3,})json\n.*?\n\1\n", re.DOTALL)


def note_name(run_id, label, begin=None):
    stamp = RUN_TIME.match(run_id)
    prefix = f"{begin:%Y-%m-%d %H%M}" if begin else "{}-{}-{} {}{}".format(*stamp.groups()[:5]) if stamp else run_id
    label = " ".join(UNSAFE_NAME.sub(" ", safe_text(label)).split()).strip(" .")
    if len(label) > 60:
        label = label[:59].rstrip() + "…"
    return f"{prefix} {label}".strip()


def iso_time(run_id):
    stamp = RUN_TIME.match(run_id)
    return "{}-{}-{}T{}:{}:{}".format(*stamp.groups()) if stamp else None


# Notes carry the machine name saved with `history host set`, and nothing when none is saved: the
# login node's own host name is not a name the Vault knows.
CONFIG = "config.json"
PLAIN_TAG = re.compile(r"[A-Za-z0-9_./-]+")


def load_config():
    try:
        value = json.loads((history_root() / CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def saved_host():
    value = load_config().get("host")
    return " ".join(value.split()) if isinstance(value, str) else ""


def host_command(words):
    config = load_config()
    if not words:
        name = saved_host()
        print(name if name else "名前は登録されていません（ノートに host は書きません）。")
        return
    if words == ["get"]:  # for the wizard: the bare name, or nothing
        print(saved_host())
        return
    if words[0] == "set" and len(words) == 2 and " ".join(words[1].split()):
        config["host"] = " ".join(words[1].split())
        message = (f"このマシンの名前を {config['host']} にしました（書き出すノートの host と host/{config['host']} のタグ）。\n"
                   "次に export-md を実行すると、書き出し済みのノートにも入ります。")
    elif words == ["unset"]:
        if config.pop("host", None) is None:
            print("名前は登録されていません。")
            return
        message = "登録した名前を消しました。ノートには host を書きません。"
    else:
        raise ValueError("使い方: agentrun history host [set NAME | unset]")
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    write_private(root / CONFIG, json.dumps(config, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(message)


def frontmatter(conversation, label, host=""):
    first, latest = conversation.first, conversation.latest
    fields = {
        "date": f"{conversation.begin:%Y-%m-%dT%H:%M:%S}" if conversation.begin else iso_time(first["run_id"]),
        "last_active": conversation.last_active.strftime("%Y-%m-%dT%H:%M:%S") if conversation.last_active else None,
        "agent": latest["agent"], "host": host or None, "mode": conversation.metadata.get("mode"), "repo": latest["repo"],
        "title": label, "run_id": first["run_id"],
        "runs": [row["run_id"] for row in conversation.runs] if conversation.resumes else None,
        "resumes": conversation.resumes or None,
        "archive_id": latest["archive_id"], "archived_at": latest["updated_at"],
        # Only in runs split by /clear: which of the run's conversations the note holds.
        "conversation_id": conversation.part[1] if conversation.part else None,
    }
    # JSON values are valid YAML flow scalars and sequences, so any text is safe here.
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items() if value]
    tags = ["agentrun"] + ([f"host/{host}"] if host else [])
    tags = ", ".join(tag if PLAIN_TAG.fullmatch(tag) else json.dumps(tag, ensure_ascii=False) for tag in tags)
    return "---\n" + "\n".join(lines) + f"\ntags: [{tags}]\n---\n"


def write_private(path, text):
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


FRONTMATTER_FIELD = re.compile(r"^(archive_id|conversation_id):[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def note_identity(path):
    """(archive_id, conversation_id or "") from a note's properties; None for a note this command did not write."""
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            head = stream.read(8192)
    except OSError:
        return None
    if not head.startswith("---\n") or "\n---" not in head[3:]:
        return None
    fields = {}
    for key, value in FRONTMATTER_FIELD.findall(head[4:head.index("\n---", 3)]):
        try:
            value = json.loads(value)  # as written; Obsidian may drop the quotes when it saves properties
        except ValueError:
            value = value.strip("'\"")
        fields[key] = str(value)
    return (fields["archive_id"], fields.get("conversation_id", "")) if fields.get("archive_id") else None


def find_notes(directory):
    """Every note in the export folder, keyed by the archive its properties name.

    Notes renamed or moved inside Obsidian are found here by what they say, not by file name.
    Hidden folders (.obsidian, .trash) are skipped.
    """
    found = {}
    for root, folders, files in os.walk(directory):
        folders[:] = sorted(f for f in folders if not f.startswith("."))
        for file in files:
            if file.endswith(".md") and not file.startswith("."):
                path = Path(root) / file
                identity = note_identity(path)
                if identity:
                    found.setdefault(identity[0], []).append((identity[1], path.relative_to(directory).as_posix()))
    return found


def ours(file, name):
    """True when the note still has the name export-md gave it (perhaps with a clash suffix)."""
    return Path(file).name == name or bool(re.fullmatch(re.escape(name[:-3]) + r" \(\d+\)\.md", Path(file).name))


def export_markdown(found, directory, hidden=()):
    """Write one Obsidian-friendly note per conversation; touch only notes this command wrote.

    A note renamed or moved inside the export folder is found again by the archive_id in its
    properties (any run of the conversation) and updated where it is, under the name it now has.
    """
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / EXPORT_STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    scanned = None
    host = saved_host()

    def locate(conversation):
        nonlocal scanned
        if scanned is None:
            scanned = find_notes(directory)
        idents = [conversation.key, *(row["archive_id"] for row in reversed(conversation.runs))]
        # In a run split by /clear, conversation_id tells its notes apart; a note without one was
        # written before the split and belongs to the first conversation.
        wanted = {conversation.part[1]} if conversation.part else {""}
        if not conversation.part or conversation.part[0] == 1:
            wanted.add("")
        matches = list(dict.fromkeys(file for ident in idents for part, file in scanned.get(ident, [])
                                     if part in wanted))
        if len(matches) > 1:
            # Several copies (a duplicated note): keep updating the one edited last.
            matches.sort(key=lambda file: (directory / file).stat().st_mtime, reverse=True)
            print(safe_text(f"同じ会話のノートが {len(matches)} 件あります。最後に変更した {matches[0]} を更新します"
                            f"（ほか: {', '.join(matches[1:])}）"))
        return matches[0] if matches else None

    # Earlier exports wrote one note per resumed run; those notes now belong to their conversation.
    merged = 0
    for conversation in found:
        if conversation.part and conversation.part[0] > 1:
            continue  # its runs' archive IDs belong to the first conversation of the run
        for row in conversation.runs:
            entry = state.get(row["archive_id"]) if row["archive_id"] != conversation.key else None
            if entry:
                (directory / entry["file"]).unlink(missing_ok=True)
                del state[row["archive_id"]]
                merged += 1
    # Notes this command wrote earlier for conversations that turned out to be empty starts.
    dropped = 0
    for conversation in hidden:
        later = conversation.part and conversation.part[0] > 1  # its runs' IDs name the first conversation
        for ident in {conversation.key} if later else {conversation.key, *(row["archive_id"] for row in conversation.runs)}:
            entry = state.pop(ident, None)
            if entry and not entry.get("renamed"):
                (directory / entry["file"]).unlink(missing_ok=True)
                dropped += 1
    titles = load_titles()
    taken = {entry["file"] for entry in state.values()}
    counts = {"new": 0, "updated": 0, "same": 0}
    followed = 0
    tz = zone()
    for conversation in reversed(found):
        latest = conversation.latest
        label = conversation.label(titles) or one_line(first_request(latest["markdown"]), 60) or latest["agent"]
        name = note_name(conversation.first["run_id"], label, conversation.begin) + ".md"
        previous = state.get(conversation.key)
        if not previous or not (directory / previous["file"]).is_file():
            # Renamed or moved in Obsidian, or the state file was lost: match by content.
            located = locate(conversation)
            if located:
                if located != (previous["file"] if previous else name):
                    followed += 1
                if previous:
                    taken.discard(previous["file"])
                # Without an earlier record (no updated_at) the note is rewritten once to be sure.
                previous = {**(previous or {}), "file": located, "renamed": not ours(located, name)}
                taken.add(located)
        version = {"updated_at": latest["updated_at"], "source": latest["archive_id"], "format": FORMAT,
                   "host": host or None}
        if previous and previous.get("renamed"):
            name = previous["file"]  # the name the user gave it stays
        else:
            folder = Path(previous["file"]).parent if previous else Path(".")
            name = (folder / name).as_posix()
            if previous and ours(previous["file"], Path(name).name) and Path(previous["file"]).parent == folder:
                name = previous["file"]  # keeps the suffix it got for a name clash earlier
        if previous and previous["file"] == name and all(previous.get(k) == v for k, v in version.items()) \
                and (directory / name).is_file():
            counts["same"] += 1
            state[conversation.key] = previous
            continue
        if not previous or previous["file"] != name:
            # Never overwrite a note this command did not write (the user's own, or another run's).
            stem, number = name[:-3], 2
            while name in taken or ((directory / name).exists() and not (previous and previous["file"] == name)):
                name, number = f"{stem} ({number}).md", number + 1
        header = ARCHIVE_HEADER.match(latest["markdown"])
        if not header:
            raise ValueError(f"unexpected archive layout: {latest['archive_id']}")
        (directory / name).parent.mkdir(parents=True, exist_ok=True)
        write_private(directory / name, frontmatter(conversation, label, host)
                      + "\n" + with_session_log(obsidian_body(latest["markdown"][header.end():], tz), conversation))
        if previous and previous["file"] != name:
            (directory / previous["file"]).unlink(missing_ok=True)  # the title changed
            taken.discard(previous["file"])
        taken.add(name)
        state[conversation.key] = {"file": name, **version}
        if previous and previous.get("renamed"):
            state[conversation.key]["renamed"] = True
        counts["updated" if previous else "new"] += 1
    write_private(state_path, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    note = f"、resume 前の重複ノートを {merged} 件まとめました" if merged else ""
    note += f"、依頼のない会話のノートを {dropped} 件削除しました" if dropped else ""
    if followed:
        note += f"、名前か場所が変わったノート {followed} 件を見つけました（今後もその名前と場所のまま更新します）"
    print(f"書き出しました: 新規 {counts['new']} 件、更新 {counts['updated']} 件、変更なし {counts['same']} 件{note} → {directory}")


def with_session_log(body, conversation):
    """The note body with the agent's session log as its first section, right after the guide comment."""
    if not conversation.session_log:
        return body
    lines = [f"- {when} {text}" if when else f"- {text}" for when, text in conversation.session_log]
    section = "## セッションログ\n\n" + "\n".join(" ".join(line.split()) for line in lines)
    if body.startswith(GUIDE + "\n\n"):
        return GUIDE + "\n\n" + section + "\n\n" + body[len(GUIDE) + 2:]
    return section + "\n\n" + body


def find_conversation(found, ident):
    """The conversation one of whose runs has this run ID (or the only one starting with it)."""
    exact = [c for c in found if c.ident == ident]
    # A plain run ID names the first conversation of the run, not the ones after /clear.
    first = [c for c in found if not (c.part and c.part[0] > 1)]
    exact = exact or [c for c in first if any(row["run_id"] == ident for row in c.runs)]
    matches = exact or [c for c in found if c.ident.startswith(ident)] \
        or [c for c in first if any(row["run_id"].startswith(ident) for row in c.runs)]
    if not matches:
        raise ValueError(f"{ident} に当たる会話がありません。ID は history list の「ID:」で確かめられます")
    if len(matches) > 1:
        raise ValueError(f"{ident} に当たる会話が {len(matches)} 件あります。もっと長く指定してください: "
                         + ", ".join(c.ident for c in matches[:5]))
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
        titles[conversation.key] = {"title": name, "run_id": conversation.ident, "renamed_at": time.time()}
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
        when = f"  最終更新 {conversation.last_active:%m-%d %H:%M}" if conversation.last_active else ""
        when_started = f"{conversation.begin:%Y-%m-%d %H:%M}" if conversation.begin else started(conversation.first["run_id"])
        print(f"{conversation.ident}\t{when_started}  "
              f"{Path(conversation.latest['repo']).name}  {one_line(label, 50)}{resumed}{when}\t{current}")


def running_runs(parent):
    """Runs whose session is still open: this directory's runs and those the launch registry knows."""
    from auth_sync import live
    from run_menu import all_runs, first_line, running_jobs
    jobs = running_jobs()
    if jobs is None:
        print("[注意] Slurm に問い合わせできないため、終了の記録がない run をすべて実行中とみなします。", file=sys.stderr)
    found = []
    for run in all_runs(parent):
        job = first_line(run / "live/slurm_job_id.txt")  # none yet: only prepared, never started
        if job and live(run) and (jobs is None or job in jobs):
            found.append(run)
    return found


def save_running(parent):
    """Save the running sessions now so export-md includes what has been said so far."""
    import history
    runs = running_runs(parent)
    if not runs:
        print("実行中のセッションはありません。保存済みの会話だけを書き出します。")
    for run in runs:
        print(f"実行中のセッションを今の内容で保存しています: {safe_text(run.name)} … ", end="", flush=True)
        try:
            history.archive(run)
        except Exception as error:  # noqa: BLE001 - one broken run must not stop the export
            print("失敗（" + safe_text(str(error)) + "）")
        else:
            print("完了")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "search", "export-md", "rename", "choices", "host"))
    parser.add_argument("words", nargs="*",
                        help="search words, the target directory for export-md, RUN_ID NEW NAME for rename, "
                             "or [set NAME | unset] for host")
    parser.add_argument("--clear", action="store_true", help="rename: go back to the title the agent wrote")
    parser.add_argument("--agent", choices=("claude", "codex", "antigravity"))
    parser.add_argument("--repo", default="", help="only conversations whose repository path contains this text")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--live", action="store_true",
                        help="export-md: save running sessions first, so they are written as they are now")
    options = parser.parse_args()
    if options.action == "list" and options.words:
        parser.error("list takes no words; use search")
    if options.action == "search" and not options.words:
        parser.error("search needs at least one word")
    if options.action == "export-md" and len(options.words) != 1:
        parser.error("export-md needs exactly one target directory")
    if options.action == "rename" and (not options.words or (options.clear and len(options.words) != 1)):
        parser.error("usage: history rename RUN_ID NEW NAME  (or: history rename RUN_ID --clear)")
    if options.live and options.action != "export-md":
        parser.error("--live is only for export-md")
    if options.limit < 1:
        parser.error("--limit must be positive")
    if options.action == "host":
        host_command(options.words)
        return 0
    if options.live:
        save_running(Path.cwd() / ".agent-runs")
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
