#!/usr/bin/env python3
"""Rebuild the example files in this folder from made-up conversations.

A fake $HOME gets one short conversation per CLI in that CLI's own transcript format; then
`agent-history sync` and `export-md` run on it as they would on a real home. No model is
called and nothing outside a temporary folder is read or written, except this folder's
archive/ and obsidian/. Run it again after changing the archive or note format:

    python3 examples/make_examples.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CLAUDE_ID = "5f0c2a9e-1b7d-4c3a-9e21-7a6b4d8c0f13"
CODEX_ID = "019abf00-3c2e-7a10-9b44-1d2e3f405162"
AGY_ID = "8e4d1c27-6a3b-4f90-b2c5-0d9e7f6a1b38"
# Fixed so the files only change when the format does.
ARCHIVED_AT = "2026-11-20T12:00:00+00:00"


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def claude(home):
    folder = home / ".claude/projects/-home-me-paper"
    base = {"sessionId": CLAUDE_ID, "cwd": "/home/me/paper"}
    write_jsonl(folder / f"{CLAUDE_ID}.jsonl", [
        {**base, "type": "user", "uuid": "u1", "timestamp": "2026-11-20T01:00:00Z",
         "message": {"role": "user", "content": "図 2 の凡例が線と重なっているので直して"}},
        {**base, "type": "assistant", "uuid": "a1", "timestamp": "2026-11-20T01:00:20Z", "message": {
            "role": "assistant", "content": [
                {"type": "thinking", "thinking": "図 2 を描いているスクリプトを探す。plot_results.py にありそう。"},
                {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": {"command": "grep -n legend plot_results.py"}}]}},
        {**base, "type": "user", "uuid": "r1", "timestamp": "2026-11-20T01:00:21Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01",
                                         "content": "42:    ax.legend(loc=\"best\")"}]}},
        {**base, "type": "assistant", "uuid": "a2", "timestamp": "2026-11-20T01:00:40Z", "message": {
            "role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_02", "name": "Edit", "input": {
                    "file_path": "/home/me/paper/plot_results.py", "old_string": "ax.legend(loc=\"best\")",
                    "new_string": "ax.legend(loc=\"upper left\", bbox_to_anchor=(1.02, 1))"}}]}},
        {**base, "type": "user", "uuid": "r2", "timestamp": "2026-11-20T01:00:41Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_02",
                                         "content": "The file /home/me/paper/plot_results.py has been updated."}]}},
        {**base, "type": "assistant", "uuid": "a3", "timestamp": "2026-11-20T01:01:00Z", "message": {
            "role": "assistant", "content": [{"type": "text", "text":
                "凡例をグラフの右外に出しました（`plot_results.py` 42 行目）。線とは重なりません。"}]}},
        {**base, "type": "user", "uuid": "u2", "timestamp": "2026-11-20T01:05:00Z",
         "message": {"role": "user", "content": "ほかの図にも同じ問題がないか探して"}},
        {**base, "type": "assistant", "uuid": "a4", "timestamp": "2026-11-20T01:05:10Z", "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": "toolu_03", "name": "Task", "input": {
                "description": "凡例の重なりを探す", "prompt": "figures/ の図で凡例が線と重なるものを探して"}}]}},
        {**base, "type": "user", "uuid": "r3", "timestamp": "2026-11-20T01:06:00Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_03",
                                         "content": "図 4 の凡例も重なっています。"}]}},
        {**base, "type": "assistant", "uuid": "a5", "timestamp": "2026-11-20T01:06:10Z", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "図 4 も同じでした。直しますか？"}]}},
        {"type": "ai-title", "aiTitle": "図の凡例の修正", "sessionId": CLAUDE_ID},
    ])
    write_jsonl(folder / CLAUDE_ID / "subagents/agent-a7f3.jsonl", [
        {"type": "user", "uuid": "s1", "timestamp": "2026-11-20T01:05:12Z",
         "message": {"role": "user", "content": "figures/ の図で凡例が線と重なるものを探して"}},
        {"type": "assistant", "uuid": "s2", "timestamp": "2026-11-20T01:05:58Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "図 4 の凡例も重なっています。"}]}}])


def codex(home):
    write_jsonl(home / f".codex/sessions/2026/11/20/rollout-2026-11-20T11-00-00-{CODEX_ID}.jsonl", [
        {"type": "session_meta", "timestamp": "2026-11-20T02:00:00Z",
         "payload": {"id": CODEX_ID, "cwd": "/home/me/model", "source": "cli", "cli_version": "0.162.1"}},
        {"type": "response_item", "timestamp": "2026-11-20T02:00:01Z", "payload": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": "テストが通るか確かめて"}]}},
        {"type": "response_item", "timestamp": "2026-11-20T02:00:05Z", "payload": {
            "type": "reasoning", "summary": [{"type": "summary_text", "text": "**テストの実行**\n\npytest で全体を流す。"}],
            "encrypted_content": "(暗号化された推論。保存されない)"}},
        {"type": "response_item", "timestamp": "2026-11-20T02:00:06Z", "payload": {
            "type": "function_call", "call_id": "call_01", "name": "exec_command",
            "arguments": json.dumps({"cmd": "pytest -q"})}},
        {"type": "response_item", "timestamp": "2026-11-20T02:00:30Z", "payload": {
            "type": "function_call_output", "call_id": "call_01",
            "output": "........F.\nFAILED tests/test_data.py::test_split - AssertionError\n1 failed, 9 passed"}},
        {"type": "response_item", "timestamp": "2026-11-20T02:01:00Z", "payload": {
            "type": "message", "role": "assistant", "content": [{"type": "output_text", "text":
                "10 件中 1 件が失敗しました（`tests/test_data.py::test_split`）。分割の比率の確認で落ちています。"}]}}])
    write_jsonl(home / ".codex/session_index.jsonl", [{"id": CODEX_ID, "thread_name": "テストの確認"}])


def antigravity(home):
    agy = home / ".gemini/antigravity-cli"
    write_jsonl(agy / "brain" / AGY_ID / ".system_generated/logs/transcript_full.jsonl", [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-11-20T03:00:00Z", "content": "<USER_REQUEST>\nREADME にインストール手順を足して\n</USER_REQUEST>"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-11-20T03:00:10Z", "thinking": "まず今の README を読む。",
         "tool_calls": [{"name": "read_file", "args": {"Path": "/home/me/docs/README.md"}}]},
        {"step_index": 2, "source": "SYSTEM", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-11-20T03:00:11Z", "content": "# docs\n\n使い方の説明。"},
        {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-11-20T03:00:40Z", "content": "README に「インストール」の節を足しました。"}])
    (agy / "cache").mkdir(parents=True)
    (agy / "cache/conversation_metadata.json").write_text(json.dumps({"conversations": {AGY_ID: {"summary": {
        "Title": "README の手順追加", "WorkspaceURIs": ["file:///home/me/docs"]}}}}))


def main(out=HERE):
    with tempfile.TemporaryDirectory(prefix="agent-history-examples-") as temp:
        home = Path(temp) / "home"
        for make in (claude, codex, antigravity):
            make(home)
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        env.update(HOME=str(home), PYTHONPATH=str(ROOT), AGENT_HISTORY_DIR=str(home / "agent-history"),
                   AGENT_HISTORY_TIMEZONE="Asia/Tokyo", AGENT_HISTORY_HOST="home-wsl")
        vault = Path(temp) / "vault"
        for args in (["sync"], ["export-md", str(vault)]):
            subprocess.run([sys.executable, "-m", "agent_history", *args], env=env, check=True,
                           capture_output=True, text=True)

        def clean(text):
            text = text.replace(str(home), "/home/me")
            text = re.sub(r'("archived_at": ")[^"]+(")', rf"\g<1>{ARCHIVED_AT}\g<2>", text)
            return re.sub(r'(archived_at: ")[^"]+(")', rf"\g<1>{ARCHIVED_AT}\g<2>", text)

        for name in ("archive", "obsidian"):
            shutil.rmtree(out / name, ignore_errors=True)
            (out / name).mkdir(parents=True)
        for path in sorted((home / "agent-history/archives").glob("*/*.md")):
            (out / "archive" / f"{path.parent.name}.md").write_text(clean(path.read_text()))
        for path in sorted(vault.glob("*.md")):
            (out / "obsidian" / path.name).write_text(clean(path.read_text()))
    return sorted(p.relative_to(out).as_posix() for p in out.glob("*/*.md"))


if __name__ == "__main__":
    print("\n".join(main()))
