#!/usr/bin/env python3
"""Run a managed worker hook; keep it inert in the isolated reviewer role.

Codex and Claude Code hand hooks their own payload (`tool_name`, `tool_input`) and
read a blocked call from exit status 2. Antigravity (`--antigravity EVENT`) sends a
camelCase payload (`toolCall.name`, `toolCall.args`) and reads a JSON decision from
stdout, so its payload is translated for the shared hooks and their answer back.
"""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

# Antigravity tool names, as the shared hooks know them.
COMMAND_TOOLS = {"run_command"}
# Hooks see read_file / write_file / edit_file with "Path"; other spellings are kept for older CLIs.
PATH_KEYS = ("Path", "TargetFile", "AbsolutePath", "FilePath", "file_path", "path", "DirectoryPath",
             "SearchPath", "SearchDirectory")
EVENTS = ("PreToolUse", "PostToolUse", "PreInvocation", "Stop")


def managed(path):
    target = Path(path).resolve()
    if (
        target.parent != Path(__file__).resolve().parent
        or target.name == Path(__file__).name
        or target.suffix != ".py"
    ):
        raise ValueError("Hook must be a sibling managed Python script")
    return target


TAIL = 1024 * 1024  # the newest steps are at the end; long conversations need not be read whole


def last_reply(transcript):
    """The newest model reply in agy's transcript log; its Stop payload carries only the path."""
    try:
        with open(transcript, "rb") as stream:
            size = stream.seek(0, 2)
            stream.seek(max(0, size - TAIL))
            lines = stream.read().decode("utf-8", errors="replace").splitlines()
    except (OSError, TypeError, ValueError):
        return ""
    for line in reversed(lines):
        try:
            step = json.loads(line)
        except ValueError:
            continue  # a step cut by the tail window or still being written
        content = step.get("content") if isinstance(step, dict) else None
        if step.get("type") == "PLANNER_RESPONSE" and isinstance(content, str) and content.strip():
            return content
    return ""


def user_turns(transcript):
    """How many user messages agy's transcript holds: the number of the current turn."""
    try:
        with open(transcript, "rb") as stream:
            return sum(1 for line in stream if b'"type": "USER_INPUT"' in line or b'"type":"USER_INPUT"' in line)
    except (OSError, TypeError, ValueError):
        return None


def translate(payload):
    """Antigravity hook input in the Claude Code / Codex shape the shared hooks read."""
    call = payload.get("toolCall") if isinstance(payload.get("toolCall"), dict) else {}
    args = call.get("args") if isinstance(call.get("args"), dict) else {}
    name = call.get("name", "")
    tool_input = {}
    if name in COMMAND_TOOLS:
        tool_input["command"] = str(args.get("CommandLine", args.get("command", "")))
    path = next((args[key] for key in PATH_KEYS if isinstance(args.get(key), str)), "")
    if path:
        tool_input["file_path"] = path
    translated = {
        "tool_name": "Bash" if name in COMMAND_TOOLS else name,
        "tool_input": tool_input,
        "cwd": payload.get("cwd", ""),
        "session_id": payload.get("conversationId", ""),
        "hook_event_name": payload.get("hookEventName", ""),
        "transcript_path": payload.get("transcriptPath", ""),
        "agent": "antigravity",
    }
    if payload.get("hookEventName") == "Stop":
        # Claude Code and Codex hand Stop hooks the reply; agy only says where its log is.
        translated["last_assistant_message"] = last_reply(payload.get("transcriptPath"))
        # Like stop_hook_active: do not hold the agent again after a Stop hook already did,
        # nor after a cancel, an error or a limit (only a normal finish asks for more work).
        translated["stop_hook_active"] = bool(payload.get("continuationActive")) or \
            payload.get("terminationReason") not in (None, "NO_TOOL_CALL", "TERMINAL_STEP_TYPE")
        turns = user_turns(payload.get("transcriptPath"))
        if turns is not None:
            translated["turn_key"] = f"{payload.get('conversationId', '')}:{turns}"
    return translated


def antigravity(event, target):
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    result = subprocess.run([sys.executable, str(target)], input=json.dumps(translate(payload)),
                            capture_output=True, text=True, check=False)
    answers = []
    for line in result.stdout.splitlines():
        try:
            answer = json.loads(line)
        except ValueError:
            continue
        if isinstance(answer, dict):
            answers.append(answer)
    if event == "Stop":
        # A shared hook's {"decision": "block"} keeps Claude Code / Codex working; agy says "continue".
        held = next((a for a in answers if a.get("decision") == "block"), None)
        print(json.dumps({"decision": "continue", "reason": str(held.get("reason") or "")}, ensure_ascii=False)
              if held else "{}")
        return 0
    if event == "PreInvocation":
        # Context a shared hook adds for the model (Claude Code's additionalContext) becomes a
        # system message agy puts before its next model call.
        added = [str(a["hookSpecificOutput"]["additionalContext"]) for a in answers
                 if isinstance(a.get("hookSpecificOutput"), dict) and a["hookSpecificOutput"].get("additionalContext")]
        print(json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": text}} for text in added]},
                         ensure_ascii=False) if added else "{}")
        return 0
    if event != "PreToolUse":
        print("{}")  # PostToolUse only observes
        return 0
    reason = ""
    for answer in answers:
        if answer.get("decision") in ("block", "deny"):
            reason = str(answer.get("reason") or "")
    if result.returncode == 2 or reason:
        reason = reason or result.stderr.strip() or "agentrun hook blocked this call"
        print(json.dumps({"decision": "deny", "reason": reason}, ensure_ascii=False))
    else:
        print(json.dumps({"decision": "allow"}))
    return 0


def main():
    arguments = sys.argv[1:]
    event = None
    if arguments[:1] == ["--antigravity"]:
        if len(arguments) != 3 or arguments[1] not in EVENTS:
            raise ValueError("Expected --antigravity EVENT HOOK")
        event, arguments = arguments[1], arguments[2:]
    if os.environ.get("AGENTRUN_ROLE") == "reviewer":
        if event:
            print("{}" if event != "PreToolUse" else json.dumps({"decision": "allow"}))
        return 0
    if len(arguments) != 1:
        raise ValueError("Expected one managed worker hook path")
    target = managed(arguments[0])
    if event:
        return antigravity(event, target)
    sys.argv = [str(target)]
    runpy.run_path(str(target), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
