"""Convert native transcripts into Markdown snapshots and a local SQLite index."""

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import html
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import tempfile


ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def history_root():
    configured = os.environ.get("AGENTRUN_HISTORY_DIR")
    return (Path(configured).expanduser() if configured else Path.home() / ".agentrun/history").resolve()


def archive_key(parent, run_id):
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run ID for history archive")
    # The same timestamp-based run ID can occur in different projects.
    project = hashlib.sha256(str(parent.resolve()).encode("utf-8")).hexdigest()[:16]
    return f"{run_id}-{project}"


def atomic_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".history-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def records(path, warnings):
    """Read the entire transcript, tolerating only a torn final JSONL record."""
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except ValueError:
                if not line.endswith("\n"):
                    warnings.add(f"{path.name}:{number}: incomplete final record omitted")
                    break
                raise ValueError(f"{path.name}:{number}: invalid JSONL record") from None
            if not isinstance(record, dict):
                raise ValueError(f"{path.name}:{number}: expected a JSON object")
            yield record


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if not isinstance(item, dict):
                continue
            if item.get("type") in ("text", "input_text", "output_text"):
                parts.append(str(item.get("text", "")))
            elif item.get("type") in ("image", "input_image", "output_image", "audio"):
                parts.append("[Non-text content: see the original transcript.]")
        return "\n".join(parts)
    return json.dumps(value, ensure_ascii=False, indent=2)


def clean(text):
    return ANSI.sub("", str(text)).replace("\x00", "")


def fence(text, language="text"):
    text = clean(text)
    width = max([2, *(len(m.group()) for m in re.finditer(r"`+", text))]) + 1
    mark = "`" * width
    return f"{mark}{language}\n{text.rstrip()}\n{mark}\n"


def detail(label, text, language="text"):
    return f"\n<details>\n<summary>{html.escape(clean(label))}</summary>\n\n{fence(text, language)}\n</details>\n"


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def within(path, root):
    return path.resolve().is_relative_to(root.resolve())


def companion_output(value, run, store, warnings):
    """Resolve only persisted run files, never arbitrary paths from a transcript."""
    name = str(value).strip()
    mappings = (("/home/sandbox/.claude/projects/", store / ".claude/projects"),
                ("/scratch/", run / "scratch"), ("/runs/", run))
    path = Path(name)
    for prefix, root in mappings:
        if name.startswith(prefix):
            path = root / name[len(prefix):]
            break
    if not path.is_absolute() or not any(within(path, root) for root in (store, run / "scratch")):
        warnings.add("An external tool output is outside persisted session/scratch storage")
        return "[External output was not archived: outside persisted storage.]"
    if not path.is_file():
        warnings.add(f"Missing companion output: {path.name}")
        return f"[Companion output is missing: {path.name}]"
    if path.suffix == ".jsonl":
        return f"[Subagent transcript is stored separately: {path.name}]"
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeError:
        warnings.add(f"Non-text companion output: {path.name}")
        return f"[Non-text companion output: {path.name}]"


def codex_transcript(path, warnings):
    metadata = {}; calls = {}; has_messages = False
    for record in records(path, warnings):
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if record.get("type") == "session_meta":
            metadata = {k: payload[k] for k in (
                "id", "session_id", "timestamp", "cli_version", "cwd", "git", "source", "originator",
                "history_mode", "parent_thread_id", "forked_from_id", "history_base") if k in payload}
        if record.get("type") == "response_item":
            if payload.get("role") in ("user", "assistant") and payload.get("type", "message") == "message":
                has_messages = True
            if payload.get("type") in ("function_call", "custom_tool_call"):
                calls[payload.get("call_id")] = payload.get("name", "tool")
    if metadata.get("history_base"):
        warnings.add(f"{path.name}: this transcript references earlier paginated/forked history")
    parts = []; seen = set()
    for record in records(path, warnings):
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            continue
        typ = payload.get("type")
        if record.get("type") == "response_item":
            if typ in ("message", None) and payload.get("role") in ("user", "assistant"):
                if payload.get("phase") == "analysis" or payload.get("channel") == "analysis":
                    continue
                text = text_content(payload.get("content", []))
                key = ("message", payload.get("id")) if payload.get("id") else None
                if text.strip() and (key is None or key not in seen):
                    parts.append(f"\n### {payload['role'].title()} · {record.get('timestamp', '')}\n\n{clean(text)}\n")
                    seen.add(key)
            elif typ in ("function_call", "custom_tool_call"):
                key = ("call", payload.get("call_id"))
                if key in seen:
                    continue
                seen.add(key)
                value = payload.get("arguments", payload.get("input", ""))
                parts.append(detail(f"Tool call: {payload.get('name', 'tool')} · {payload.get('call_id', '')} · {record.get('timestamp', '')}",
                                    text_content(value)))
            elif typ in ("function_call_output", "custom_tool_call_output"):
                parts.append(detail(f"Tool result: {calls.get(payload.get('call_id'), 'tool')} · {payload.get('call_id', '')} · {record.get('timestamp', '')}",
                                    text_content(payload.get("output", ""))))
        elif record.get("type") == "event_msg":
            item = payload.get("item", {})
            if typ == "item_completed" and isinstance(item, dict):
                kind = item.get("type")
                if kind == "CommandExecution":
                    fields = {k: item[k] for k in ("id", "command", "cwd", "exit_code", "status", "duration", "process_id") if k in item}
                    if record.get("timestamp"):
                        fields["timestamp"] = record["timestamp"]
                    body = json_text(fields)
                    # Newer CLI versions keep only aggregated output. Older ones
                    # can retain more text here than in the formatted tool result.
                    separate = any(isinstance(item.get(k), str) and item[k] for k in ("stdout", "stderr"))
                    if separate:
                        for key in ("stdout", "stderr"):
                            if isinstance(item.get(key), str):
                                body += f"\n\n{key}:\n{item[key]}"
                    else:
                        body += "\n\nCombined output:\n" + str(item.get("aggregated_output") or item.get("formatted_output") or "")
                    parts.append(detail(f"Command execution · {item.get('id', '')}", body))
                elif kind == "FileChange":
                    parts.append(detail("File changes", json_text({k: item[k] for k in ("changes", "status", "stdout", "stderr") if k in item}), "json"))
            elif not has_messages and typ in ("user_message", "agent_message"):
                role = "User" if typ == "user_message" else "Assistant"
                text = payload.get("message", "")
                if isinstance(text, str) and text.strip():
                    parts.append(f"\n### {role} · {record.get('timestamp', '')}\n\n{clean(text)}\n")
        elif record.get("type") == "compacted":
            parts.append("\n_Context compacted; original records above remain part of this archive._\n")
    return metadata, "".join(parts)


def claude_transcript(path, run, store, warnings):
    metadata = {}; parts = []; seen = set(); calls = {}
    for record in records(path, warnings):
        if record.get("type") not in ("user", "assistant"):
            continue
        for key in ("sessionId", "version", "cwd", "gitBranch", "agentId", "isSidechain"):
            if key in record:
                metadata[key] = record[key]
        message = record.get("message", {})
        if not isinstance(message, dict):
            continue
        role = message.get("role", record["type"])
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            key = (record.get("uuid"), index)
            if record.get("uuid") and key in seen:
                continue
            seen.add(key)
            typ = block.get("type")
            if typ == "text" and role in ("user", "assistant") and not record.get("isMeta"):
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    parts.append(f"\n### {role.title()} · {record.get('timestamp', '')}\n\n{clean(text)}\n")
            elif typ == "tool_use":
                ident = block.get("id", "")
                calls[ident] = block.get("name", "tool")
                parts.append(detail(f"Tool call: {calls[ident]} · {ident} · {record.get('timestamp', '')}", json_text(block.get("input", {})), "json"))
            elif typ == "tool_result":
                ident = block.get("tool_use_id", "")
                text = text_content(block.get("content", ""))
                result = record.get("toolUseResult")
                body = f"is_error: {block.get('is_error', 'unknown')}\n\n{text}"
                if isinstance(result, dict):
                    for name in ("stdout", "stderr"):
                        if isinstance(result.get(name), str) and result[name] != text:
                            body += f"\n\n{name}:\n{result[name]}"
                    extra = {k: result[k] for k in ("interrupted", "backgroundTaskId", "status", "structuredPatch", "filePath", "outputFile") if k in result}
                    if extra:
                        body += "\n\nStructured result:\n" + json_text(extra)
                    if result.get("outputFile"):
                        body += "\n\nCompanion output:\n" + companion_output(result["outputFile"], run, store, warnings)
                # Large synchronous tool results can refer to a spilled file.
                for name in re.findall(r"(?im)^\s*(?:Full output saved to|Output saved to):\s*(/[^\r\n<]+)", text):
                    body += "\n\nFull output:\n" + companion_output(name, run, store, warnings)
                parts.append(detail(f"Tool result: {calls.get(ident, 'tool')} · {ident} · {record.get('timestamp', '')}", body))
    return metadata, "".join(parts)


@contextmanager
def archive_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".lock").open("a") as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def export_run(run, data, store):
    """Archive all native sessions, including subagents and /new sessions in a run."""
    archive_id = archive_key(run.parent, data["run_id"])
    root = history_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = root / "runs" / archive_id
    with archive_lock(target):
        warnings = set(); transcript_metadata = []; parts = []
        if data["agent"] == "codex":
            paths = sorted({*store.glob(".codex/sessions/**/*.jsonl"), *store.glob(".codex/archived_sessions/**/*.jsonl")})
        elif data["agent"] == "claude":
            paths = sorted(store.glob(".claude/projects/**/*.jsonl"))
        else:
            raise ValueError("Unsupported agent for history export")
        for path in paths:
            if not within(path, store):
                raise ValueError("Transcript points outside its session store")
            if data["agent"] == "codex":
                metadata, body = codex_transcript(path, warnings)
            else:
                metadata, body = claude_transcript(path, run, store, warnings)
            metadata["file"] = str(path.relative_to(store))
            transcript_metadata.append(metadata)
            parts.append(f"\n## Session: {path.stem}\n\n{fence(json_text(metadata), 'json')}{body}")
        info = {k: data[k] for k in ("run_id", "agent", "repo", "mode", "session_key", "parent_run_id") if k in data}
        info.update(archive_id=archive_id, run_parent=str(run.parent.resolve()),
                    launcher_cwd=data.get("launcher_cwd"),
                    archived_at=datetime.now(timezone.utc).isoformat(), archive_host=socket.gethostname(),
                    transcripts=transcript_metadata, warnings=sorted(warnings))
        markdown = "# Conversation archive\n\n" + fence(json_text({k: v for k, v in info.items() if k != "transcripts"}), "json")
        markdown += "".join(parts) if parts else "\nNo persisted conversation records were found.\n"
        if warnings:
            markdown += "\n## Archive notes\n\n" + "".join(f"- {clean(w)}\n" for w in sorted(warnings))
        markdown_path = target / "conversation.md"
        atomic_text(markdown_path, markdown)
        atomic_text(target / "metadata.json", json_text(info) + "\n")
        database = root / "index.sqlite3"
        with sqlite3.connect(database, timeout=30) as db:
            os.chmod(database, 0o600)
            db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                archive_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, run_parent TEXT NOT NULL,
                agent TEXT NOT NULL, repo TEXT NOT NULL, launcher_cwd TEXT,
                session_key TEXT NOT NULL, markdown_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL, markdown TEXT NOT NULL, updated_at TEXT NOT NULL)""")
            db.execute("""INSERT INTO conversations (
                archive_id, run_id, run_parent, agent, repo, launcher_cwd, session_key,
                markdown_path, metadata_json, markdown, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(archive_id) DO UPDATE SET
                launcher_cwd=excluded.launcher_cwd,
                markdown_path=excluded.markdown_path, metadata_json=excluded.metadata_json,
                markdown=excluded.markdown, updated_at=excluded.updated_at""",
                (archive_id, data["run_id"], info["run_parent"], data["agent"], data["repo"],
                 info["launcher_cwd"], data["session_key"], str(markdown_path),
                 json_text(info), markdown, info["archived_at"]))
        status = {"status": "success" if paths else "empty", "archive_host": info["archive_host"],
                  "archive_id": archive_id,
                  "markdown": str(markdown_path), "database": str(database),
                  "transcripts": len(paths), "warnings": sorted(warnings)}
        atomic_text(run / "live/history_export.json", json_text(status) + "\n")
        return status
