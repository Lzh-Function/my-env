#!/usr/bin/env python3
"""List, search and export archived conversations from the shared history database.

The database is opened read-only; export-md only writes into the directory it is given.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

from history_export import history_root
from sessions import safe_text

RUN_TIME = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
# Messages the CLIs inject as "user" turns; they are not what the person typed.
INJECTED = re.compile(r"\s*(?:<[a-z_]+>|# AGENTS\.md instructions)")
USER_TURN = re.compile(r"^### User · [^\n]*\n\n(.*?)(?=\n### |\n## |\n<details>|\Z)", re.MULTILINE | re.DOTALL)


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


def first_request(markdown):
    for match in USER_TURN.finditer(markdown):
        text = match.group(1).strip()
        if text and not INJECTED.match(text):
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


def rows(db, words, agent, repo):
    query = ("SELECT archive_id, run_id, run_parent, agent, repo, markdown_path, metadata_json, markdown, updated_at "
             "FROM conversations WHERE 1=1")
    params = []
    for word in words:
        query += " AND instr(lower(markdown), lower(?)) > 0"
        params.append(word)
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    if repo:
        query += " AND instr(repo, ?) > 0"
        params.append(repo)
    # Run IDs start with the launch time, so this is newest first.
    return db.execute(query + " ORDER BY run_id DESC, archive_id", params).fetchall()


def show(found, words, limit):
    if not found:
        print("該当する会話はありません。" if words else "保存された会話はまだありません。")
        return
    for _archive_id, run_id, run_parent, agent, repo, markdown_path, metadata_json, markdown, _updated in found[:limit]:
        metadata = json.loads(metadata_json)
        heading = "  ".join(part for part in (
            started(run_id), agent, metadata.get("mode", ""), Path(repo).name or repo,
            one_line(title(run_parent, run_id, metadata), 50)) if part)
        print(safe_text(heading))
        request = first_request(markdown)
        if request:
            print("    最初の依頼: " + one_line(request, 70))
        for text in snippets(markdown, words):
            print("    一致: " + one_line(text, 110))
        print("    " + safe_text(short_path(markdown_path)))
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


def frontmatter(run_id, agent, repo, metadata, label, updated):
    stamp = RUN_TIME.match(run_id)
    fields = {
        "date": "{}-{}-{}T{}:{}:{}".format(*stamp.groups()) if stamp else None,
        "agent": agent, "mode": metadata.get("mode"), "repo": repo, "title": label,
        "run_id": run_id, "archive_id": metadata.get("archive_id"), "archived_at": updated,
    }
    # JSON strings are valid YAML double-quoted scalars, so any text is safe here.
    lines = [f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in fields.items() if value]
    return "---\n" + "\n".join(lines) + "\ntags: [agentrun]\n---\n"


def write_private(path, text):
    temporary = path.with_name("." + path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(text)
    temporary.replace(path)


def export_markdown(found, directory):
    """Write one Obsidian-friendly note per conversation; touch only notes this command wrote."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_path = directory / EXPORT_STATE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
    taken = {entry["file"] for entry in state.values()}
    counts = {"new": 0, "updated": 0, "same": 0}
    for archive_id, run_id, run_parent, agent, repo, _path, metadata_json, markdown, updated in reversed(found):
        metadata = json.loads(metadata_json)
        label = title(run_parent, run_id, metadata) or one_line(first_request(markdown), 60) or agent
        name = note_name(run_id, label) + ".md"
        previous = state.get(archive_id)
        if previous and re.fullmatch(re.escape(name[:-3]) + r" \(\d+\)\.md", previous["file"]):
            name = previous["file"]  # keeps the suffix it got for a name clash earlier
        if previous and previous["updated_at"] == updated and previous["file"] == name \
                and (directory / name).is_file():
            counts["same"] += 1
            continue
        if not previous or previous["file"] != name:
            # Never overwrite a note this command did not write (the user's own, or another run's).
            stem, number = name[:-3], 2
            while name in taken or ((directory / name).exists() and not (previous and previous["file"] == name)):
                name, number = f"{stem} ({number}).md", number + 1
        header = ARCHIVE_HEADER.match(markdown)
        if not header:
            raise ValueError(f"unexpected archive layout: {archive_id}")
        write_private(directory / name, frontmatter(run_id, agent, repo, metadata, label, updated)
                      + markdown[header.end():])
        if previous and previous["file"] != name:
            (directory / previous["file"]).unlink(missing_ok=True)  # the title changed
            taken.discard(previous["file"])
        taken.add(name)
        state[archive_id] = {"file": name, "updated_at": updated}
        counts["updated" if previous else "new"] += 1
    write_private(state_path, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    print(f"書き出しました: 新規 {counts['new']} 件、更新 {counts['updated']} 件、変更なし {counts['same']} 件 → {directory}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("list", "search", "export-md"))
    parser.add_argument("words", nargs="*", help="search words, or the target directory for export-md")
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
    if options.limit < 1:
        parser.error("--limit must be positive")
    db = connect()
    if db is None:
        print("保存された会話はまだありません（" + str(history_root()) + "）。")
        return 0
    words = [] if options.action == "export-md" else options.words
    try:
        found = rows(db, words, options.agent, options.repo)
    finally:
        db.close()
    if options.action == "export-md":
        export_markdown(found, Path(options.words[0]).expanduser().resolve())
    else:
        show(found, words, options.limit)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, sqlite3.Error) as error:
        print("history: " + str(error), file=sys.stderr)
        sys.exit(2)
