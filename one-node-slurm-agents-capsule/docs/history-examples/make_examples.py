#!/usr/bin/env python3
"""Rebuild the example files in this folder from made-up agentrun runs.

In a temporary folder, three runs (Codex, Claude Code, Antigravity) get a short conversation
in their CLI's own transcript format, and the Codex run is resumed once. They are archived as
agentrun does when a run ends, and `agentrun history export-md` writes the notes. No model or
Slurm is used. Run it again after changing the archive or note format:

    python3 docs/history-examples/make_examples.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "runtime/agentrun"))
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
# Where the example pretends the runs live; the temporary folder is renamed to this.
SHOWN_HOME = "/home/me"
ARCHIVED_AT = "2026-11-20T12:00:00+00:00"
CODEX_ID = "019abf00-3c2e-7a10-9b44-1d2e3f405162"
CLAUDE_ID = "5f0c2a9e-1b7d-4c3a-9e21-7a6b4d8c0f13"
AGY_ID = "8e4d1c27-6a3b-4f90-b2c5-0d9e7f6a1b38"


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def codex_message(role, text, stamp):
    kind = "output_text" if role == "assistant" else "input_text"
    return {"type": "response_item", "timestamp": stamp,
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": text}]}}


def codex_records(resumed):
    records = [
        {"type": "session_meta", "timestamp": "2026-11-19T09:00:00Z",
         "payload": {"id": CODEX_ID, "cwd": "/workspace", "source": "cli", "cli_version": "0.162.1"}},
        codex_message("user", "学習率を 1e-4 に下げて再学習して", "2026-11-19T09:00:01Z"),
        {"type": "response_item", "timestamp": "2026-11-19T09:00:05Z", "payload": {
            "type": "reasoning", "summary": [{"type": "summary_text", "text": "**設定の変更**\n\nconfig.yaml の lr を変えて train.py を流す。"}],
            "encrypted_content": "(暗号化された推論。保存されない)"}},
        {"type": "response_item", "timestamp": "2026-11-19T09:00:06Z", "payload": {
            "type": "function_call", "call_id": "call_01", "name": "exec_command",
            "arguments": json.dumps({"cmd": "sed -i 's/lr: 3e-4/lr: 1e-4/' config.yaml && python train.py"})}},
        {"type": "response_item", "timestamp": "2026-11-19T09:40:00Z", "payload": {
            "type": "function_call_output", "call_id": "call_01", "output": "epoch 10/10  val_loss 0.31"}},
        codex_message("assistant", "学習率を 1e-4 にして再学習しました。val_loss は 0.31 です。", "2026-11-19T09:40:10Z"),
    ]
    if resumed:
        records += [
            codex_message("user", "前回の結果を表にまとめて", "2026-11-20T01:00:00Z"),
            codex_message("assistant", "| lr | val_loss |\n| --- | --- |\n| 3e-4 | 0.35 |\n| 1e-4 | 0.31 |",
                          "2026-11-20T01:00:20Z"),
        ]
    return records


def claude_records():
    base = {"sessionId": CLAUDE_ID, "cwd": "/workspace"}
    return [
        {**base, "type": "user", "uuid": "u1", "timestamp": "2026-11-20T02:00:00Z",
         "message": {"role": "user", "content": "図 2 の凡例が線と重なっているので直して"}},
        {**base, "type": "assistant", "uuid": "a1", "timestamp": "2026-11-20T02:00:20Z", "message": {
            "role": "assistant", "content": [
                {"type": "thinking", "thinking": "図 2 を描いているスクリプトを探す。"},
                {"type": "tool_use", "id": "toolu_01", "name": "Bash", "input": {"command": "grep -n legend plot_results.py"}}]}},
        {**base, "type": "user", "uuid": "r1", "timestamp": "2026-11-20T02:00:21Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_01",
                                         "content": "42:    ax.legend(loc=\"best\")"}]}},
        {**base, "type": "assistant", "uuid": "a2", "timestamp": "2026-11-20T02:01:00Z", "message": {
            "role": "assistant", "content": [{"type": "text", "text":
                "凡例をグラフの右外に出しました（`plot_results.py` 42 行目）。"}]}},
        {"type": "ai-title", "aiTitle": "図の凡例の修正", "sessionId": CLAUDE_ID},
    ]


def agy_records():
    return [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-11-20T03:00:00Z", "content": "<USER_REQUEST>\nREADME にインストール手順を足して\n</USER_REQUEST>"},
        {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-11-20T03:00:10Z", "thinking": "まず今の README を読む。",
         "tool_calls": [{"name": "read_file", "args": {"Path": "/workspace/README.md"}}]},
        {"step_index": 2, "source": "SYSTEM", "type": "GENERIC", "status": "DONE",
         "created_at": "2026-11-20T03:00:11Z", "content": "# docs\n\n使い方の説明。"},
        {"step_index": 3, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-11-20T03:00:40Z", "content": "README に「インストール」の節を足しました。"},
    ]


def build(temp):
    import history as collector
    import sessions

    parent = temp / ".agent-runs"
    parent.mkdir()

    def start(run_id, agent, repo, source=None):
        run = parent / run_id
        run.mkdir()
        (temp / repo).mkdir(exist_ok=True)
        sessions.init(run, agent, str(temp / repo), "assist", source)
        return run, sessions.state_dir(run, sessions.manifest(run))

    def log(run, *lines):
        # What the session log hooks have the agent write (Japan time).
        (run / "live").mkdir(exist_ok=True)
        (run / "live/session_log.md").write_text("".join(f"- {line}\n" for line in lines))

    def title(run, text):
        (run / "artifacts").mkdir(exist_ok=True)
        (run / "artifacts/run_title.txt").write_text(text + "\n")

    first, store = start("20261119_180000_assist_codex", "codex", "model")
    rollout = store / f".codex/sessions/2026/11/19/rollout-2026-11-19T18-00-00-{CODEX_ID}.jsonl"
    write_jsonl(rollout, codex_records(resumed=False))
    title(first, "学習率を下げた再学習")
    log(first, "2026-11-19 18:20 （途中）lr を 1e-4 に変えて再学習を始めた",
        "2026-11-19 18:40 lr 1e-4 で再学習し val_loss 0.31 を確認した")
    collector.archive(first)
    # `agentrun --resume`: a new run that continues the same Codex conversation.
    resumed, _ = start("20261120_100000_resume-assist_codex", "codex", "model", first)
    write_jsonl(rollout, codex_records(resumed=True))
    log(resumed, "2026-11-20 10:01 前回の学習結果を表にまとめた")
    collector.archive(resumed)

    run, store = start("20261120_110000_assist_claude", "claude", "paper")
    write_jsonl(store / ".claude/projects/-workspace" / f"{CLAUDE_ID}.jsonl", claude_records())
    title(run, "図の凡例の修正")
    log(run, "2026-11-20 11:01 図2の凡例を枠の外に移して再描画した")
    collector.archive(run)

    run, store = start("20261120_120000_assist_antigravity", "antigravity", "docs")
    write_jsonl(store / ".gemini/antigravity-cli/brain" / AGY_ID / ".system_generated/logs/transcript_full.jsonl",
                agy_records())
    title(run, "README の手順追加")
    log(run, "2026-11-20 12:01 README にインストール手順を追記した")
    collector.archive(run)
    return parent


def main(out=HERE):
    with tempfile.TemporaryDirectory(prefix="agentrun-history-examples-") as name:
        temp = Path(name).resolve()
        env = dict(os.environ, AGENTRUN_HISTORY_DIR=str(temp / "history"), AGENTRUN_TIMEZONE="Asia/Tokyo")
        os.environ.update(AGENTRUN_HISTORY_DIR=env["AGENTRUN_HISTORY_DIR"])
        here = os.getcwd()
        os.chdir(temp)  # recorded as the folder agentrun was started from
        try:
            parent = build(temp)
        finally:
            os.chdir(here)
        vault = temp / "vault"
        subprocess.run([str(LAUNCHER), "history", "export-md", str(vault)], cwd=temp, env=env, check=True,
                       capture_output=True, text=True)

        # Archive IDs carry a hash of the runs folder; show the hash the pretend folder would have.
        real = hashlib.sha256(str(parent).encode()).hexdigest()[:16]
        shown = hashlib.sha256(f"{SHOWN_HOME}/.agent-runs".encode()).hexdigest()[:16]

        def clean(text):
            text = text.replace(str(temp), SHOWN_HOME).replace(real, shown)
            text = text.replace(f'"archive_host": "{socket.gethostname()}"', '"archive_host": "login01"')
            text = re.sub(r'("(?:archived_at|created_at|updated_at)": )("[^"]+"|[0-9.]+)', rf'\1"{ARCHIVED_AT}"', text)
            return re.sub(r'^(archived_at: )"[^"]+"', rf'\1"{ARCHIVED_AT}"', text, flags=re.MULTILINE)

        for folder in ("archive", "obsidian"):
            shutil.rmtree(out / folder, ignore_errors=True)
            (out / folder).mkdir(parents=True)
        for path in sorted((temp / "history/runs").glob("*/*")):
            if path.name in ("conversation.md", "metadata.json", "session_log.md"):
                target = out / "archive" / path.parent.name.replace(real, shown) / path.name
                target.parent.mkdir(exist_ok=True)
                target.write_text(clean(path.read_text()))
        for path in sorted(vault.glob("*.md")):
            (out / "obsidian" / path.name).write_text(clean(path.read_text()))
    return sorted(p.relative_to(out).as_posix() for folder in ("archive", "obsidian")
                  for p in (out / folder).rglob("*") if p.is_file())


if __name__ == "__main__":
    print("\n".join(main()))
