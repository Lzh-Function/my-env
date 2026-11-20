"""Render each CLI's native transcript as Markdown (Claude Code, Codex, Antigravity).

Ported from agentrun's history export; only the parsers and their helpers are kept here.
"""

import html
import json
import os
from pathlib import Path
import re
import tempfile


ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
PROVIDERS = ("codex", "claude", "antigravity")
# agy wraps what the person typed with context it adds for the model.
AGY_REQUEST = re.compile(r"<USER_REQUEST>\n?(.*?)\n?</USER_REQUEST>", re.DOTALL)
TURN_STAMP = re.compile(r"^### (?:User|Assistant) · (\S+)$", re.MULTILINE)


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


def thinking(stamp, text):
    """The model's visible reasoning, kept as its own folded detail (never a conversation turn)."""
    return detail(f"Thinking · {stamp}", text)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def within(path, root):
    return path.resolve().is_relative_to(root.resolve())


def companion_roots():
    """Where Claude Code keeps long tool output: its projects folder and its temp folder."""
    return (Path.home() / ".claude", Path(tempfile.gettempdir()) / f"claude-{os.getuid()}")


def companion_output(value, warnings):
    """Read only files Claude Code itself wrote, never arbitrary paths named in a transcript."""
    path = Path(str(value).strip())
    if not path.is_absolute() or not any(within(path, root) for root in companion_roots()):
        warnings.add("An external tool output is outside Claude Code's own folders")
        return "[External output was not archived: outside Claude Code's own folders.]"
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


class Parser:
    """Renders one transcript record by record and can resume later from saved state.

    `feed` takes one JSON record and returns the Markdown it adds. `state()` returns
    everything needed to continue with the records appended after it (JSON-safe), so a
    long conversation is not parsed from the start on every turn.
    """

    def __init__(self, path, state=None):
        self.path = Path(path)
        state = state or {}
        self.metadata = state.get("metadata", {})
        self.warnings = set(state.get("warnings", []))
        self.seen = set(state.get("seen", []))
        self.calls = state.get("calls", {})
        self.restore(state)

    def restore(self, state):
        pass

    def state(self):
        return {"metadata": self.metadata, "warnings": sorted(self.warnings), "seen": sorted(self.seen),
                "calls": self.calls, **self.extra_state()}

    def extra_state(self):
        return {}

    def feed(self, record):
        raise NotImplementedError

    def finish(self):
        """Warnings that depend on the whole file so far."""


class CodexParser(Parser):
    def restore(self, state):
        # Old Codex versions logged messages only as events; those are used only when the
        # file has no response_item messages, so both forms are kept until that is known.
        self.has_messages = state.get("has_messages", False)

    def extra_state(self):
        return {"has_messages": self.has_messages}

    def feed(self, record):
        payload = record.get("payload", {})
        if not isinstance(payload, dict):
            return []
        parts = []
        typ = payload.get("type")
        if record.get("type") == "session_meta":
            self.metadata = {k: payload[k] for k in (
                "id", "session_id", "timestamp", "cli_version", "cwd", "git", "source", "originator",
                "history_mode", "parent_thread_id", "forked_from_id", "history_base") if k in payload}
        if record.get("type") == "response_item":
            if typ in ("message", None) and payload.get("role") in ("user", "assistant"):
                if payload.get("phase") == "analysis" or payload.get("channel") == "analysis":
                    text = text_content(payload.get("content", []))
                    if text.strip():
                        parts.append(thinking(record.get("timestamp", ""), text))
                    return parts
                self.has_messages = True
                text = text_content(payload.get("content", []))
                key = "message:" + str(payload["id"]) if payload.get("id") else None
                if text.strip() and (key is None or key not in self.seen):
                    parts.append(f"\n### {payload['role'].title()} · {record.get('timestamp', '')}\n\n{clean(text)}\n")
                    if key:
                        self.seen.add(key)
            elif typ == "reasoning":
                # Codex keeps the reasoning itself encrypted; only its readable summary, if any, is kept.
                texts = [item.get("text", "") for key in ("summary", "content")
                         for item in payload.get(key) or [] if isinstance(item, dict)
                         and item.get("type") in ("summary_text", "reasoning_text", "text")]
                text = "\n\n".join(t for t in texts if isinstance(t, str) and t.strip())
                if text:
                    parts.append(thinking(record.get("timestamp", ""), text))
            elif typ in ("function_call", "custom_tool_call"):
                key = "call:" + str(payload.get("call_id"))
                if key in self.seen:
                    return parts
                self.seen.add(key)
                self.calls[str(payload.get("call_id"))] = payload.get("name", "tool")
                value = payload.get("arguments", payload.get("input", ""))
                parts.append(detail(f"Tool call: {payload.get('name', 'tool')} · {payload.get('call_id', '')} · {record.get('timestamp', '')}",
                                    text_content(value)))
            elif typ in ("function_call_output", "custom_tool_call_output"):
                parts.append(detail(f"Tool result: {self.calls.get(str(payload.get('call_id')), 'tool')} · {payload.get('call_id', '')} · {record.get('timestamp', '')}",
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
            elif typ in ("user_message", "agent_message"):
                role = "User" if typ == "user_message" else "Assistant"
                text = payload.get("message", "")
                if isinstance(text, str) and text.strip():
                    parts.append(EventMessage(f"\n### {role} · {record.get('timestamp', '')}\n\n{clean(text)}\n"))
        elif record.get("type") == "compacted":
            parts.append("\n_Context compacted; original records above remain part of this archive._\n")
        return parts

    def finish(self):
        if self.metadata.get("history_base"):
            self.warnings.add(f"{self.path.name}: this transcript references earlier paginated/forked history")


class EventMessage(str):
    """A Codex message logged only as an event; shown only when the file has no other messages."""


class ClaudeParser(Parser):
    def restore(self, state):
        # Working directory and name ride along, so the file is read once for everything.
        self.cwd = state.get("cwd", "")
        self.custom_title = state.get("custom_title", "")
        self.ai_title = state.get("ai_title", "")

    def extra_state(self):
        return {"cwd": self.cwd, "custom_title": self.custom_title, "ai_title": self.ai_title}

    @property
    def title(self):
        # A name the person gave (/rename) wins over the newest title Claude Code generated.
        return self.custom_title or self.ai_title

    def feed(self, record):
        if not self.cwd and isinstance(record.get("cwd"), str):
            self.cwd = record["cwd"]
        if record.get("type") == "custom-title" and isinstance(record.get("customTitle"), str):
            self.custom_title = record["customTitle"]
        elif record.get("type") == "ai-title" and isinstance(record.get("aiTitle"), str):
            self.ai_title = record["aiTitle"]
        if record.get("type") not in ("user", "assistant"):
            return []
        for key in ("sessionId", "version", "cwd", "gitBranch", "agentId", "isSidechain"):
            if key in record:
                self.metadata[key] = record[key]
        message = record.get("message", {})
        if not isinstance(message, dict):
            return []
        role = message.get("role", record["type"])
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            return []
        parts = []
        for index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            key = f"{record.get('uuid')}:{index}"
            if record.get("uuid") and key in self.seen:
                continue
            if record.get("uuid"):
                self.seen.add(key)
            typ = block.get("type")
            if typ == "text" and role in ("user", "assistant") and not record.get("isMeta"):
                text = block.get("text", "")
                if isinstance(text, str) and text.strip():
                    parts.append(f"\n### {role.title()} · {record.get('timestamp', '')}\n\n{clean(text)}\n")
            elif typ == "thinking" and isinstance(block.get("thinking"), str) and block["thinking"].strip():
                parts.append(thinking(record.get("timestamp", ""), block["thinking"]))
            elif typ == "tool_use":
                ident = str(block.get("id", ""))
                self.calls[ident] = block.get("name", "tool")
                parts.append(detail(f"Tool call: {self.calls[ident]} · {ident} · {record.get('timestamp', '')}", json_text(block.get("input", {})), "json"))
            elif typ == "tool_result":
                ident = str(block.get("tool_use_id", ""))
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
                        body += "\n\nCompanion output:\n" + companion_output(result["outputFile"], self.warnings)
                # Large synchronous tool results can refer to a spilled file.
                for name in re.findall(r"(?im)^\s*(?:Full output saved to|Output saved to):\s*(/[^\r\n<]+)", text):
                    body += "\n\nFull output:\n" + companion_output(name, self.warnings)
                parts.append(detail(f"Tool result: {self.calls.get(ident, 'tool')} · {ident} · {record.get('timestamp', '')}", body))
        return parts


AGY_TIMES = re.compile(r"^(?:Created At|Completed At): .*\n?", re.MULTILINE)


class AgyParser(Parser):
    """agy's transcript log: one JSON object per step, in step order.

    USER_INPUT steps are what the person sent, and PLANNER_RESPONSE steps are the model's
    thinking, reply and the tools it called. Each tool's result is a later step of its own
    (GENERIC, status ERROR when it failed), in the order the calls were made.
    """

    def restore(self, state):
        self.pending = state.get("pending", [])
        self.metadata.setdefault("conversation_id", self.path.parents[2].name)
        self.metadata["transcript"] = self.path.name

    def extra_state(self):
        return {"pending": self.pending}

    def feed(self, record):
        kind = str(record.get("type", "STEP"))
        stamp = record.get("created_at", "")
        step = record.get("step_index", "")
        content = record.get("content") if isinstance(record.get("content"), str) else ""
        if isinstance(record.get("model"), str):
            self.metadata.setdefault("model", record["model"])
        parts = []
        if kind == "USER_INPUT":
            found = AGY_REQUEST.search(content)
            text = found.group(1) if found else content
            if record.get("source") not in (None, "USER_EXPLICIT"):
                self.metadata.setdefault("started_by", record.get("source"))
            if text.strip():
                parts.append(f"\n### User · {stamp}\n\n{clean(text)}\n")
        elif kind == "PLANNER_RESPONSE":
            if isinstance(record.get("thinking"), str) and record["thinking"].strip():
                parts.append(thinking(stamp, record["thinking"]))
            if content.strip():
                parts.append(f"\n### Assistant · {stamp}\n\n{clean(content)}\n")
            for call in record.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                name = str(call.get("name", "tool"))
                self.pending.append(name)
                parts.append(detail(f"Tool call: {name} · {step} · {stamp}", json_text(call.get("args", {})), "json"))
        elif kind == "GENERIC":
            name = self.pending.pop(0) if self.pending else "tool"
            failed = record.get("status") == "ERROR"
            body = AGY_TIMES.sub("", content).strip()
            if failed and record.get("error") and record["error"] not in body:
                body = str(record["error"]) + ("\n\n" + body if body else "")
            parts.append(detail(f"Tool result: {name} · {step} · {stamp}", f"is_error: {failed}\n\n{body}"))
        elif kind == "SYSTEM_MESSAGE":
            # Reminders agy adds on its own; the model reads them, the person did not write them.
            parts.append(detail(f"System message · {step} · {stamp}", content))
        else:
            body = {k: v for k, v in record.items() if k not in ("type", "created_at", "thinking")}
            parts.append(detail(f"Tool result: {kind.lower()} · {step} · {stamp}", json_text(body), "json"))
        return parts


PARSERS = {"codex": CodexParser, "claude": ClaudeParser, "antigravity": AgyParser}
