"""Conversation export and host-only batch collection with synthetic transcripts."""

import contextlib
from datetime import timezone
import io
import json
import os
import re
import signal
import shutil
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime/agentrun"))
import history as collector
import history_export
import obsidian_note
import sessions

LAUNCHER = ROOT / "runtime/agentrun/agentrun"
ID = "12345678-1234-1234-1234-123456789abc"


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


def message(role, text, **extra):
    return {"type": "response_item", "payload": {"type": "message", "role": role,
            "content": [{"type": "output_text" if role == "assistant" else "input_text", "text": text}], **extra}}


def command_event(**extra):
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "CommandExecution", "id": "exec-1", "command": ["bash", "-c", "printf result"],
        "cwd": "/workspace", "status": "completed", "exit_code": 0,
        "stdout": None, "stderr": None, "aggregated_output": "combined output", **extra}}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="conversation archive with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.history_root = self.root / "central history"
        environment = patch.dict(os.environ, AGENTRUN_HISTORY_DIR=str(self.history_root))
        environment.start()
        self.addCleanup(environment.stop)
        self.parent = self.root / ".agent-runs"
        self.parent.mkdir()
        self.run = self.parent / "first-run"
        self.run.mkdir()

    def initialize(self, agent="codex"):
        sessions.init(self.run, agent, str(self.root), "assist")
        self.data = sessions.manifest(self.run)
        self.store = sessions.state_dir(self.run, self.data)
        return self.store

    def codex(self, records=None):
        self.initialize()
        self.path = self.store / ".codex/sessions/2026/10/16/rollout.jsonl"
        write_jsonl(self.path, records or [
            {"type": "session_meta", "payload": {"id": ID, "cli_version": "fixture", "source": "cli", "originator": "fixture-cli"}},
            message("user", "first request"), message("assistant", "first answer"),
        ])

    def markdown(self):
        status = json.loads((self.run / "live/history_export.json").read_text())
        return Path(status["markdown"]).read_text()

    def database_rows(self):
        with sqlite3.connect(self.history_root / "index.sqlite3") as db:
            return db.execute("SELECT run_id, markdown_path, markdown, metadata_json FROM conversations").fetchall()

    def test_codex_full_transcript_commands_and_optional_fields(self):
        self.codex([
            {"type": "session_meta", "payload": {"id": ID, "source": {"subagent": {"other": "guardian"}},
             "originator": "fixture", "cli_version": "0.test", "base_instructions": "DO NOT EXPORT POLICY"}},
            message("user", "first request"),
            message("developer", "DO NOT EXPORT POLICY"),
            message("assistant", "CODEX ANALYSIS THOUGHT", phase="analysis"),
            {"type": "response_item", "payload": {"type": "reasoning", "encrypted_content": "DO NOT EXPORT REASONING",
                                                  "summary": [{"type": "summary_text", "text": "CODEX REASONING SUMMARY"}]}},
            {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "call_id": "call-1", "input": "tools.exec_command({cmd: 'printf result'})"}},
            command_event(aggregated_output="full output\n" + "x" * 300000, formatted_output="short output"),
            {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "call-1", "output": [
                {"type": "input_text", "text": "Warning: truncated output"},
                {"type": "input_image", "image_url": "data:image/png;base64,DO_NOT_EXPORT_IMAGE"}]}},
            command_event(id="exec-2", stdout="separate stdout", stderr="separate stderr", aggregated_output="merged"),
            {"type": "compacted", "payload": {"replacement_history": [message("developer", "DO NOT EXPORT COMPACTION POLICY")]}},
            message("assistant", "final answer", id="answer-1"),
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "final answer"}},
            message("assistant", "final answer", id="answer-1"),
        ])
        result = collector.archive(self.run)
        text = self.markdown()
        for expected in ("first request", "full output", "x" * 300000, "separate stdout", "separate stderr",
                         "printf result", "exec-1", "Warning: truncated output", "guardian"):
            self.assertIn(expected, text)
        # Readable thinking is kept as its own detail; encrypted reasoning never is.
        for kept in ("CODEX ANALYSIS THOUGHT", "CODEX REASONING SUMMARY"):
            self.assertIn(kept, text)
        self.assertEqual(text.count("<summary>Thinking"), 2)
        for excluded in ("DO NOT EXPORT", "DO_NOT_EXPORT_IMAGE", "short output"):
            self.assertNotIn(excluded, text)
        self.assertEqual(text.count("final answer"), 1)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["archive_host"], socket.gethostname())
        self.assertTrue(self.path.exists())
        row = self.database_rows()[0]
        self.assertEqual(row[2], text)
        self.assertIsInstance(json.loads(row[3])["transcripts"][0]["source"], dict)
        self.assertEqual(Path(row[1]).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.history_root / "index.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_list_and_search_show_readable_runs_newest_first(self):
        def archived(name, repo, request, answer, title=None):
            run = self.parent / name
            run.mkdir()
            (self.root / repo).mkdir(exist_ok=True)
            sessions.init(run, "codex", str(self.root / repo), "assist")
            store = sessions.state_dir(run, sessions.manifest(run))
            write_jsonl(store / ".codex/sessions/rollout.jsonl", [
                message("user", "<environment_context>injected</environment_context>"),
                message("user", request), message("assistant", answer)])
            if title:
                (run / "artifacts").mkdir(exist_ok=True)
                (run / "artifacts/run_title.txt").write_text(title + "\n")
            collector.archive(run)

        def agentrun(*args):
            result = subprocess.run([str(LAUNCHER), "history", *args], cwd=self.root / "elsewhere",
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        (self.root / "elsewhere").mkdir()
        self.assertIn("保存された会話はまだありません", agentrun("list"))
        archived("20261113_120000_assist_codex", "chem model", "学習率を下げて再学習して", "loss は 0.31 まで下がった",
                 title="retrained chem model")
        archived("20261114_093000_assist_codex", "slides", "発表スライドを直して", "図 3 を差し替えた")
        out = agentrun("list")
        newest, oldest = out.index("2026-11-14 09:30"), out.index("2026-11-13 12:00")
        self.assertLess(newest, oldest)
        self.assertIn("2026-11-13 12:00  codex  assist  chem model  retrained chem model", out)
        self.assertIn("最初の依頼: 学習率を下げて再学習して", out)
        self.assertNotIn("environment_context", out)
        self.assertIn("conversation.md", out)
        out = agentrun("search", "LOSS")
        self.assertIn("chem model", out)
        self.assertNotIn("slides", out)
        self.assertIn("一致: ", out)
        self.assertIn("該当する会話はありません", agentrun("search", "loss", "スライド"))
        self.assertIn("slides", agentrun("list", "--repo", "slides"))
        self.assertNotIn("chem model", agentrun("list", "--repo", "slides"))
        self.assertIn("ほかに 1 件", agentrun("list", "--limit", "1"))

    def test_export_md_writes_named_notes_and_only_rewrites_its_own_changed_notes(self):
        def archived(name, request, answer, title=None):
            run = self.parent / name
            run.mkdir(exist_ok=True)
            if not (run / "session.json").exists():
                sessions.init(run, "codex", str(self.root), "assist")
            store = sessions.state_dir(run, sessions.manifest(run))
            write_jsonl(store / ".codex/sessions/rollout.jsonl", [message("user", request), message("assistant", answer)])
            if title:
                (run / "artifacts").mkdir(exist_ok=True)
                (run / "artifacts/run_title.txt").write_text(title + "\n")
            collector.archive(run)

        def export():
            result = subprocess.run([str(LAUNCHER), "history", "export-md", str(vault)], cwd=self.root,
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        vault = self.root / "vault/agent history"
        archived("20261113_120000_assist_codex", "学習率を下げて", "loss は 0.31", title="retrained: chem/model")
        archived("20261114_093000_assist_codex", "発表スライドを直して", "図 3 を差し替えた")
        vault.mkdir(parents=True)
        (vault / "2026-11-14 0930 発表スライドを直して.md").write_text("my own note\n")
        self.assertIn("新規 2 件、更新 0 件、変更なし 0 件", export())
        note = (vault / "2026-11-13 1200 retrained chem model.md").read_text()
        self.assertTrue(note.startswith('---\ndate: "2026-11-13T12:00:00"\nlast_active: "2026-11-13T12:00:00"\n'
                                        'agent: "codex"\nmode: "assist"\n'), note[:200])
        self.assertIn('title: "retrained: chem/model"\n', note)
        self.assertIn("tags: [agentrun]\n---\n", note)
        self.assertNotIn("# Conversation archive", note)
        self.assertIn("loss は 0.31", note)
        # The user's note with the same name is kept; the export takes the next free name.
        self.assertEqual((vault / "2026-11-14 0930 発表スライドを直して.md").read_text(), "my own note\n")
        self.assertIn("図 3", (vault / "2026-11-14 0930 発表スライドを直して (2).md").read_text())
        self.assertIn("新規 0 件、更新 0 件、変更なし 2 件", export())
        archived("20261113_120000_assist_codex", "学習率を下げて", "loss は 0.29", title="retrained again")
        self.assertIn("新規 0 件、更新 1 件、変更なし 1 件", export())
        self.assertFalse((vault / "2026-11-13 1200 retrained chem model.md").exists())
        self.assertIn("loss は 0.29", (vault / "2026-11-13 1200 retrained again.md").read_text())
        self.assertEqual((vault / "2026-11-13 1200 retrained again.md").stat().st_mode & 0o777, 0o600)
        # Notes written by an older layout are rewritten once, even when the archive did not change.
        state_path = vault / ".agentrun-export.json"
        state = json.loads(state_path.read_text())
        for entry in state.values():
            entry.pop("format")
        state_path.write_text(json.dumps(state))
        self.assertIn("新規 0 件、更新 2 件、変更なし 0 件", export())
        self.assertIn("新規 0 件、更新 0 件、変更なし 2 件", export())

    def test_resumed_runs_are_one_conversation_named_by_the_newest_title(self):
        def agentrun(*args):
            result = subprocess.run([str(LAUNCHER), "history", *args], cwd=self.root,
                                    capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout

        first = self.parent / "20261021_170331_assist_codex"
        first.mkdir()
        sessions.init(first, "codex", str(self.root), "assist")
        rollout = sessions.state_dir(first, sessions.manifest(first)) / ".codex/sessions/rollout.jsonl"
        meta = {"type": "session_meta", "payload": {"id": ID}}
        write_jsonl(rollout, [meta, message("user", "図を直して"), message("assistant", "直した")])
        (first / "artifacts").mkdir()
        (first / "artifacts/run_title.txt").write_text("fixed figures\n")
        collector.archive(first)
        vault = self.root / "vault"
        # An export from before grouping wrote one note per run; fake that for the resumed run below.
        resumed = self.parent / "20261105_151417_resume-assist_codex_X"
        resumed.mkdir()
        sessions.init(resumed, "codex", str(self.root), "assist", first)
        write_jsonl(rollout, [meta, message("user", "図を直して"), message("assistant", "直した"),
                              message("user", "続き: 表も"), message("assistant", "表も直した")])
        (resumed / "artifacts").mkdir()
        (resumed / "artifacts/run_title.txt").write_text("")  # resumes often write no title
        collector.archive(resumed)
        vault.mkdir()
        old_id = history_export.archive_key(self.parent, resumed.name)
        (vault / "2026-11-05 1514 図を直して.md").write_text("old per-run note\n")
        (vault / ".agentrun-export.json").write_text(json.dumps(
            {old_id: {"file": "2026-11-05 1514 図を直して.md", "updated_at": "x"}}))

        listing = agentrun("list")
        self.assertEqual(listing.count("最初の依頼: 図を直して"), 1, listing)
        self.assertIn("2026-10-21 17:03  codex  assist", listing)
        self.assertIn("fixed figures", listing)
        self.assertIn("最終更新: 2026-11-05 15:14（resume 1 回）", listing)
        self.assertIn("一致: ", agentrun("search", "表も直した"))
        self.assertIn("新規 1 件、更新 0 件、変更なし 0 件、resume 前の重複ノートを 1 件まとめました", agentrun("export-md", str(vault)))
        self.assertEqual(sorted(p.name for p in vault.iterdir()), [".agentrun-export.json", "2026-10-21 1703 fixed figures.md"])
        note = (vault / "2026-10-21 1703 fixed figures.md").read_text()
        self.assertIn('last_active: "2026-11-05T15:14:17"\n', note)
        self.assertIn('runs: ["20261021_170331_assist_codex", "20261105_151417_resume-assist_codex_X"]\nresumes: 1\n', note)
        self.assertIn("表も直した", note)
        # A newer title from a later resume replaces the name, and the note follows it.
        (resumed / "artifacts/run_title.txt").write_text("fixed figures and tables\n")
        collector.archive(resumed)
        self.assertIn("更新 1 件", agentrun("export-md", str(vault)))
        self.assertTrue((vault / "2026-10-21 1703 fixed figures and tables.md").is_file())
        self.assertFalse((vault / "2026-10-21 1703 fixed figures.md").exists())
        # Renamed and moved in Obsidian: found again by its archive_id and updated under the user's name.
        mine = vault / "papers/図と表の修正メモ.md"
        mine.parent.mkdir()
        (vault / "2026-10-21 1703 fixed figures and tables.md").rename(mine)
        mine.write_text(re.sub(r'archive_id: "([^"]+)"', r"archive_id: \1", mine.read_text()))  # Obsidian drops quotes
        self.assertIn("名前か場所が変わったノート 1 件", agentrun("export-md", str(vault)))
        # A later title change keeps the user's name.
        (resumed / "artifacts/run_title.txt").write_text("another title\n")
        collector.archive(resumed)
        self.assertIn("更新 1 件", agentrun("export-md", str(vault)))
        self.assertIn('title: "another title"', mine.read_text())
        self.assertEqual(sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md")), ["papers/図と表の修正メモ.md"])
        (vault / ".agentrun-export.json").unlink()  # losing the state file no longer duplicates notes
        self.assertIn("新規 0 件", agentrun("export-md", str(vault)))
        self.assertEqual(sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*.md")), ["papers/図と表の修正メモ.md"])
        self.assertIn("表も直した", mine.read_text())

    def history_cli(self, *args, expected=0):
        result = subprocess.run([str(LAUNCHER), "history", *args], cwd=self.root,
                                capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def archived_run(self, name, messages, title=None):
        run = self.parent / name
        run.mkdir()
        sessions.init(run, "codex", str(self.root), "assist")
        store = sessions.state_dir(run, sessions.manifest(run))
        write_jsonl(store / ".codex/sessions/rollout.jsonl",
                    [{"type": "session_meta", "payload": {"id": ID}}, *messages])
        if title is not None:
            (run / "artifacts").mkdir()
            (run / "artifacts/run_title.txt").write_text(title + "\n")
        collector.archive(run)
        return run

    def test_sessions_where_nobody_asked_anything_are_left_out(self):
        start = ("You are running inside an HPC agent capsule.\n\nMode: assist\n\n"
                 "Wait for the user's first instruction. Do not read files.")
        goal = ("/goal You are running inside an HPC agent capsule.\n\nMode: experiment\n\n"
                "User goal:\ntrain the baseline\n\nRequired outputs (paths are inside the capsule):\n- x")
        exit_command = "<command-name>/exit</command-name>\n<command-message>exit</command-message>\n<command-args></command-args>"
        # Opened and closed without a request: the agent still answered the start prompt once.
        self.archived_run("20261101_100000_assist_codex", [message("user", start), message("assistant", "指示を待ちます")])
        self.archived_run("20261102_100000_assist_codex", [
            message("user", start), message("assistant", "指示を待ちます"), message("user", exit_command),
            message("user", "<environment_context>\n</environment_context>")])
        self.archived_run("20261103_100000_assist_codex", [
            message("user", start), message("assistant", "指示を待ちます"), message("user", "図を直して"),
            message("assistant", "直した")])
        self.archived_run("20261104_100000_experiment_codex", [message("user", goal), message("assistant", "done")])
        self.archived_run("20261105_100000_assist_codex", [
            message("user", start), message("assistant", "指示を待ちます"),
            message("user", "<command-name>/review-paper</command-name>\n<command-args></command-args>")])
        listing = self.history_cli("list")
        self.assertNotIn("20261101_100000", listing)
        self.assertNotIn("20261102_100000", listing)
        self.assertIn("ID: 20261103_100000_assist_codex", listing)
        self.assertIn("ID: 20261104_100000_experiment_codex", listing)  # a batch goal is a request
        self.assertIn("ID: 20261105_100000_assist_codex", listing)  # so is a skill command
        self.assertIn("最初の依頼: 図を直して", listing)
        self.assertIn("最初の依頼: train the baseline", listing)
        self.assertNotIn("You are running inside", listing)
        self.assertIn("該当する会話はありません", self.history_cli("search", "指示を待ちます", "/exit"))
        # Notes an earlier export wrote for those empty starts are removed on the next export.
        vault = self.root / "vault"
        vault.mkdir()
        empty_id = history_export.archive_key(self.parent, "20261101_100000_assist_codex")
        (vault / "2026-11-01 1000 empty.md").write_text("old\n")
        (vault / ".agentrun-export.json").write_text(json.dumps({empty_id: {"file": "2026-11-01 1000 empty.md"}}))
        self.assertIn("新規 3 件、更新 0 件、変更なし 0 件、依頼のない会話のノートを 1 件削除しました",
                      self.history_cli("export-md", str(vault)))
        self.assertFalse((vault / "2026-11-01 1000 empty.md").exists())
        self.assertIn("2026-11-03 1000 図を直して.md", [p.name for p in vault.iterdir()])

    def real_prompt(self, mode, launch, goal="train the baseline", agent="codex"):
        """The start prompt exactly as the launcher writes it, so wording changes reach these tests."""
        path = self.root / f"prompt-{mode}-{launch}-{agent}.txt"
        script = 'source "$1"; write_prompt "$2" "$3" "$6" /repo "$4" "$5" 32000M 4 0 01:00:00 ""'
        subprocess.run(["bash", "-c", script, "bash", str(LAUNCHER), str(path), mode, goal, launch, agent],
                       check=True, capture_output=True, timeout=30, env=dict(os.environ, GH_ENV_FILE=""))
        return path.read_text()

    def test_empty_start_detection_follows_the_launchers_real_prompts(self):
        # If this fails after editing write_prompt, update CAPSULE_PROMPT, INTERACTIVE_PROMPT or GOAL
        # in history_index.py so empty starts stay hidden and batch goals stay visible.
        import history_index
        interactive = self.real_prompt("assist", "interactive")
        self.assertFalse(history_index.spoken(interactive), "the interactive start prompt counts as a request")
        for mode in ("assist", "experiment", "campaign"):
            with self.subTest(mode=mode):
                prompt = self.real_prompt(mode, "batch")
                self.assertTrue(history_index.spoken(prompt), f"a {mode} batch prompt is hidden as empty")
        # End to end: the same text as the first user turn of archived conversations.
        self.archived_run("20261101_100000_assist_codex", [message("user", interactive), message("assistant", "待ちます")])
        self.archived_run("20261102_100000_experiment_codex", [
            message("user", self.real_prompt("experiment", "batch", goal="train the baseline\nwith two seeds")),
            message("assistant", "done")])
        listing = self.history_cli("list")
        self.assertNotIn("20261101_100000", listing)
        self.assertIn("最初の依頼: train the baseline with two seeds", listing)

    def agy_run(self, name, steps, reviewer_steps=None):
        """An archived agy worker run, with an optional agy reviewer transcript."""
        run = self.parent / name
        run.mkdir()
        sessions.init(run, "antigravity", str(self.root), name.split("_")[2])
        store = sessions.state_dir(run, sessions.manifest(run))
        logs = store / ".gemini/antigravity-cli/brain" / ID / ".system_generated/logs"
        write_jsonl(logs / "transcript.jsonl", steps[:1])  # the short log is ignored when the full one exists
        write_jsonl(logs / "transcript_full.jsonl", steps)
        if reviewer_steps:
            other = "22345678-1234-1234-1234-123456789abc"
            path = store / "reviewers/antigravity/.gemini/antigravity-cli/brain" / other / ".system_generated/logs"
            write_jsonl(path / "transcript.jsonl", reviewer_steps)
        collector.archive(run)
        self.run = run
        return run

    def test_antigravity_transcripts_archive_turns_tools_and_reviewers(self):
        def request(text, stamp="2026-11-20T05:44:27Z"):
            return {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
                    "created_at": stamp,
                    "content": f"<USER_REQUEST>\n{text}\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\nHIDDEN TIME\n</ADDITIONAL_METADATA>"}
        steps = [
            request("calc.py を直して"),
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-11-20T05:44:30Z", "model": "gemini-4-neon-high", "thinking": "HIDDEN THOUGHT",
             "tool_calls": [{"name": "edit_file", "args": {"Path": "/workspace/calc.py", "Target": "a - b",
                                                           "Replacement": "a + b"}},
                            {"name": "run_command", "args": {"CommandLine": "pip install x"}}]},
            {"step_index": 2, "source": "MODEL", "type": "GENERIC", "status": "DONE", "created_at": "2026-11-20T05:44:31Z",
             "content": "Created At: 2026-11-20T05:44:31Z\nCompleted At: 2026-11-20T05:44:31Z\nMade 1 replacement"},
            {"step_index": 3, "source": "MODEL", "type": "GENERIC", "status": "ERROR", "created_at": "2026-11-20T05:44:32Z",
             "error": "tool call denied by pre-tool hook: pip is forbidden",
             "content": "Created At: 2026-11-20T05:44:32Z\nEncountered error in step execution"},
            {"step_index": 4, "source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE",
             "created_at": "2026-11-20T05:44:33Z", "content": "Reminder: work efficiently."},
            {"step_index": 5, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-11-20T05:44:40Z", "content": "直しました。pip は止められました。"},
        ]
        reviewer = [request("Review the snapshot"),
                    {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
                     "created_at": "2026-11-20T05:45:00Z", "content": "No findings."}]
        self.agy_run("20261120_144341_experiment_antigravity", steps, reviewer)
        markdown = self.markdown()
        self.assertIn(f"## Session: {ID} (worker, antigravity)", markdown)
        self.assertIn("## Session: 22345678-1234-1234-1234-123456789abc (reviewer, antigravity)", markdown)
        self.assertIn("### User · 2026-11-20T05:44:27Z\n\ncalc.py を直して\n", markdown)
        self.assertIn("### Assistant · 2026-11-20T05:44:40Z\n\n直しました。pip は止められました。", markdown)
        self.assertIn("<summary>Tool call: edit_file · 1 · 2026-11-20T05:44:30Z</summary>", markdown)
        # Results follow their calls in order; a failed call keeps its error.
        self.assertIn("<summary>Tool result: edit_file · 2 · 2026-11-20T05:44:31Z</summary>", markdown)
        self.assertIn("<summary>Tool result: run_command · 3 · 2026-11-20T05:44:32Z</summary>", markdown)
        self.assertIn("is_error: True\n\ntool call denied by pre-tool hook: pip is forbidden", markdown)
        self.assertIn("<summary>System message · 4 · 2026-11-20T05:44:33Z</summary>", markdown)
        self.assertIn("<summary>Thinking · 2026-11-20T05:44:30Z</summary>", markdown)
        self.assertIn("HIDDEN THOUGHT", markdown)
        for hidden in ("HIDDEN TIME", "Created At:"):
            self.assertNotIn(hidden, markdown)
        self.assertIn('"model": "gemini-4-neon-high"', markdown)
        # Listing, filters and the Obsidian note treat agy like the other agents.
        listing = self.history_cli("list", "--agent", "antigravity")
        self.assertIn("antigravity  experiment", listing)
        self.assertIn("最初の依頼: calc.py を直して", listing)
        self.assertIn("該当する会話はありません", self.history_cli("search", "calc.py", "--agent", "codex"))
        vault = self.root / "vault"
        self.history_cli("export-md", str(vault))
        note = next(vault.glob("*.md")).read_text()
        self.assertIn("## 作業担当のセッション（Antigravity）", note)
        self.assertIn("## 監査役のセッション（Antigravity）", note)
        self.assertIn("🤖 Antigravity", note)
        self.assertIn("> [!example]- 🔧 edit_file", note)
        self.assertIn("> [!failure]- ↩️ 結果: run_command（エラー）", note)
        self.assertIn("> [!note]- 📣 システムメッセージ", note)
        # Thinking is folded under its own marker, so it can be dropped apart from tool output.
        block = note[note.index("%% agentrun:begin thinking %%"):]
        self.assertIn("> [!abstract]- 💭 思考", block[:200])
        self.assertIn("HIDDEN THOUGHT", block[:300])
        stripped = subprocess.run(["sed", "/^%% agentrun:begin /,/^%% agentrun:end %%$/d"], input=note,
                                  capture_output=True, text=True).stdout
        self.assertNotIn("HIDDEN THOUGHT", stripped)

    def test_antigravity_empty_interactive_start_is_hidden(self):
        import history_index
        interactive = self.real_prompt("assist", "interactive", agent="antigravity")
        self.assertFalse(history_index.spoken(interactive))
        self.agy_run("20261120_090000_assist_antigravity", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": "2026-11-20T00:00:00Z", "content": f"<USER_REQUEST>\n{interactive}\n</USER_REQUEST>"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-11-20T00:00:05Z", "content": "指示を待ちます。"}])
        self.assertNotIn("20261120_090000", self.history_cli("list"))

    def test_last_activity_is_the_newest_message_and_orders_the_list(self):
        def timed(role, text, stamp):
            return {**message(role, text), "timestamp": stamp}

        # Started earlier but still in use: its newest message (UTC) decides, shown in Japan time.
        self.archived_run("20261101_100000_assist_codex", [
            timed("user", "長い作業", "2026-11-01T01:00:00Z"), timed("assistant", "続けます", "2026-11-17T13:40:00Z")])
        self.archived_run("20261110_100000_assist_codex", [
            timed("user", "短い作業", "2026-11-10T01:00:00Z"), timed("assistant", "済み", "2026-11-10T01:05:00Z")])
        listing = self.history_cli("list")
        self.assertIn("最終更新: 2026-11-17 22:40\n", listing)
        self.assertIn("最終更新: 2026-11-10 10:05\n", listing)
        self.assertLess(listing.index("長い作業"), listing.index("短い作業"))
        vault = self.root / "vault"
        self.history_cli("export-md", str(vault))
        self.assertIn('last_active: "2026-11-17T22:40:00"', (vault / "2026-11-01 1000 長い作業.md").read_text())
        choices = subprocess.run([sys.executable, str(ROOT / "runtime/agentrun/history_index.py"), "choices"],
                                 capture_output=True, text=True, timeout=10, check=True).stdout
        self.assertIn("最終更新 11-17 22:40", choices)

    def test_rename_names_the_conversation_until_cleared(self):
        self.archived_run("20261103_100000_assist_codex", [message("user", "図を直して"), message("assistant", "直した")],
                          title="fixed figures")
        self.archived_run("20261103_110000_assist_codex", [message("user", "表を直して"), message("assistant", "直した")])
        self.assertIn("2 件あります", self.history_cli("rename", "20261103", "x", expected=2))
        self.assertIn("当たる会話がありません", self.history_cli("rename", "20991231", "x", expected=2))
        self.assertIn("名前を変えました: fixed figures → 発表の図 修正",
                      self.history_cli("rename", "20261103_1000", "発表の図", " 修正"))
        self.assertIn("発表の図 修正", self.history_cli("list"))
        vault = self.root / "vault"
        self.history_cli("export-md", str(vault))
        self.assertTrue((vault / "2026-11-03 1000 発表の図 修正.md").is_file())
        self.assertIn('title: "発表の図 修正"', (vault / "2026-11-03 1000 発表の図 修正.md").read_text())
        self.assertIn("名前を変えました: 発表の図 修正 → fixed figures",
                      self.history_cli("rename", "20261103_100000_assist_codex", "--clear"))
        self.assertIn("更新 1 件", self.history_cli("export-md", str(vault)))
        self.assertTrue((vault / "2026-11-03 1000 fixed figures.md").is_file())
        self.assertFalse((vault / "2026-11-03 1000 発表の図 修正.md").exists())

    def test_obsidian_note_folds_tools_and_keeps_messages_out_of_the_outline(self):
        archive = (
            f"\n## Session: abc (worker, claude)\n\n{history_export.fence(history_export.json_text({'cwd': '/workspace'}), 'json')}"
            "\n### User · 2026-11-18T05:30:12Z\n\n<environment_context>\n</environment_context>\n"
            "\n### User · 2026-11-18T05:30:13Z\n\nfix [[slides]]\n"
            "\n### Assistant · 2026-11-18T05:31:00Z\n\n## Result\n\n#include and `#keep`\n\n```sh\n# comment\n\n\nls\n```\n"
            + history_export.detail("Tool call: Bash · t1 · 2026-11-18T05:31:05Z", "{}", "json")
            + history_export.detail("Tool result: Bash · t1 · 2026-11-18T05:31:06Z", "is_error: True\n\nboom ```x```")
            + "\n_Context compacted; original records above remain part of this archive._\n")
        note = obsidian_note.obsidian_body(archive, timezone.utc)
        self.assertIn("## 作業担当のセッション（Claude）\n\n%% agentrun:begin session %%\n\n> [!info]- セッション情報\n> ```json\n", note)
        self.assertIn("> [!note]- ⚙️ 自動で挿入されたメッセージ · 11/18 05:30\n> <environment_context>", note)
        self.assertIn("### 🧑 ユーザー · 11/18 05:30\n\nfix \\[\\[slides]]", note)
        self.assertIn("### 🤖 Claude · 11/18 05:31\n\n**Result**\n\n\\#include and `#keep`", note)
        self.assertIn("```sh\n# comment\n\n\nls\n```", note)  # code is left exactly as it was
        self.assertIn("> [!example]- 🔧 Bash · 11/18 05:31\n> ```json\n> {}\n> ```", note)
        self.assertIn("> [!failure]- ↩️ 結果: Bash（エラー） · 11/18 05:31\n> ````text\n> boom ```x```\n> ````", note)
        self.assertIn("> [!info] ここで文脈が圧縮されました", note)
        self.assertNotIn("<details>", note)
        self.assertIn("11/18 14:30", obsidian_note.obsidian_body(archive))  # Japan time by default
        # Everything folded sits between marker lines, so a reader can keep only the conversation.
        self.assertTrue(note.startswith("<!-- agentrun: "))
        self.assertIn("%% agentrun:begin tool %%\n\n> [!example]- 🔧 Bash", note)
        self.assertIn("```\n\n%% agentrun:end %%", note)
        kept, inside = [], False
        for line in note.splitlines():
            if line.startswith("%% agentrun:begin "):
                inside = True
            elif line == "%% agentrun:end %%":
                inside = False
            elif not inside:
                kept.append(line)
        conversation = "\n".join(kept)
        for gone in ("[!info]- セッション情報", "🔧 Bash", "boom", "environment_context"):
            self.assertNotIn(gone, conversation)
        for kept_text in ("fix \\[\\[slides]]", "\\#include", "```sh\n# comment"):
            self.assertIn(kept_text, conversation)
        # A message cannot start a marker line, in prose or in a code block.
        spoof = ("\n### Assistant · 2026-11-18T05:31:00Z\n\n%% agentrun:begin tool %%\n\n"
                 "```text\n%% agentrun:begin tool %%\n```\n")
        rendered = obsidian_note.obsidian_body(spoof, timezone.utc)
        self.assertNotIn("\n%% agentrun:begin", rendered)
        self.assertIn("\\%\\% agentrun:begin tool \\%\\%", rendered)
        self.assertIn("```text\n %% agentrun:begin tool %%\n```", rendered)

    def test_default_root_and_override(self):
        with patch.dict(os.environ, HOME=str(self.root / "host-home")):
            os.environ.pop("AGENTRUN_HISTORY_DIR")
            self.assertEqual(history_export.history_root(), self.root / "host-home/.agentrun/history")
            os.environ["AGENTRUN_HISTORY_DIR"] = "~/custom-history"
            self.assertEqual(history_export.history_root(), self.root / "host-home/custom-history")

    def test_projects_share_index_without_run_id_collisions_or_local_copies(self):
        self.codex()
        first = collector.archive(self.run)
        other = self.root / "other project/.agent-runs" / self.run.name
        other.mkdir(parents=True)
        # Even the same --repo may be launched using distinct run parents.
        sessions.init(other, "codex", str(self.root), "assist")
        store = sessions.state_dir(other, sessions.manifest(other))
        write_jsonl(store / ".codex/sessions/other.jsonl", [message("assistant", "other project answer")])
        second = collector.archive(other)
        self.assertEqual(first["database"], second["database"])
        self.assertNotEqual(first["archive_id"], second["archive_id"])
        self.assertNotEqual(first["markdown"], second["markdown"])
        self.assertNotEqual(collector.control_path(self.run.parent, self.run.name),
                            collector.control_path(other.parent, other.name))
        self.assertEqual(len(self.database_rows()), 2)
        self.assertIn("first answer", Path(first["markdown"]).read_text())
        self.assertIn("other project answer", Path(second["markdown"]).read_text())
        for run in (self.run, other):
            self.assertFalse((run.parent / ".history").exists())
            self.assertFalse((run / "artifacts/conversation.md").exists())
        # The archive does not depend on the project surviving afterwards.
        shutil.rmtree(self.parent)
        self.assertIn("first answer", Path(first["markdown"]).read_text())
        self.assertEqual(len(self.database_rows()), 2)

    def test_launcher_cwd_is_independent_of_repo_and_export_location(self):
        launcher_cwd = self.root / "launch directory"
        launcher_cwd.mkdir()
        repo = self.root / "target repository"
        repo.mkdir()
        result = subprocess.run([sys.executable, str(ROOT / "runtime/agentrun/sessions.py"),
                                 "init", str(self.run), "codex", str(repo), "assist"],
                                cwd=launcher_cwd, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sessions.manifest(self.run)["launcher_cwd"], str(launcher_cwd))
        collector.archive(self.run)
        metadata = json.loads(self.database_rows()[0][3])
        self.assertEqual(metadata["launcher_cwd"], str(launcher_cwd))
        self.assertEqual(metadata["repo"], str(repo))
        self.assertIn(str(launcher_cwd), self.markdown())
        with sqlite3.connect(self.history_root / "index.sqlite3") as db:
            self.assertEqual(db.execute("SELECT launcher_cwd, repo FROM conversations").fetchone(),
                             (str(launcher_cwd), str(repo)))

    def test_old_manifest_has_unknown_launcher_cwd(self):
        self.codex()
        self.data.pop("launcher_cwd")
        sessions.save(self.run, self.data)
        collector.archive(self.run)
        self.assertIsNone(json.loads(self.database_rows()[0][3])["launcher_cwd"])
        with sqlite3.connect(self.history_root / "index.sqlite3") as db:
            self.assertIsNone(db.execute("SELECT launcher_cwd FROM conversations").fetchone()[0])

    def test_function_output_string_and_event_only_legacy_messages(self):
        self.codex([
            {"type": "session_meta", "payload": {"id": ID}},
            {"type": "event_msg", "payload": {"type": "user_message", "message": "legacy request"}},
            {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command", "call_id": "call-1", "arguments": '{"cmd":"pwd"}'}},
            {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "call-1", "output": "legacy result"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "legacy answer"}},
        ])
        collector.archive(self.run)
        for value in ("legacy request", "legacy answer", "legacy result", "exec_command"):
            self.assertIn(value, self.markdown())

    def test_export_md_live_saves_running_sessions_first(self):
        def run(name, request, job, finished=False):
            path = self.parent / name
            path.mkdir()
            sessions.init(path, "codex", str(self.root), "assist")
            store = sessions.state_dir(path, sessions.manifest(path))
            write_jsonl(store / ".codex/sessions/rollout.jsonl", [
                {"type": "session_meta", "payload": {"id": ID}},
                message("user", request), message("assistant", "作業中です")])
            (path / "live").mkdir(exist_ok=True)
            (path / "live/slurm_job_id.txt").write_text(job + "\n")
            if finished:
                (path / "live/session_finished.txt").write_text("done\n")

        run("20261118_090000_assist_codex", "いま進行中の依頼", "4242")
        run("20261118_080000_assist_codex", "ジョブが消えた依頼", "9999")
        run("20261118_070000_assist_codex", "終わった依頼", "4243", finished=True)
        run("20261118_060000_assist_codex", "準備だけの依頼", "")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "squeue").write_text("#!/bin/sh\nprintf '4242\\n4243\\n'\n")
        (bin_dir / "squeue").chmod(0o755)
        home = self.root / "home"
        home.mkdir()
        environment = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}:{os.environ['PATH']}"}

        def export(*options):
            result = subprocess.run([str(LAUNCHER), "history", "export-md", str(self.root / "vault"), *options],
                                    cwd=self.root, env=environment, capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return result.stdout + result.stderr

        self.assertIn("保存された会話はまだありません", export())
        output = export("--live")
        self.assertIn("実行中のセッションを今の内容で保存しています: 20261118_090000_assist_codex … 完了", output)
        self.assertNotIn("20261118_080000", output)
        self.assertNotIn("20261118_070000", output)
        self.assertNotIn("20261118_060000", output)
        notes = [path.read_text() for path in (self.root / "vault").glob("*.md")]
        self.assertEqual(len(notes), 1)
        self.assertIn("いま進行中の依頼", notes[0])
        self.assertIn("--live is only for export-md", self.history_cli("list", "--live", expected=2))

    def test_daily_schedule_is_one_crontab_line_that_exports_and_reports_failures(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        table = self.root / "crontab.txt"
        (bin_dir / "crontab").write_text(
            '#!/bin/sh\nif [ "$1" = -l ]; then [ -f "$TABLE" ] || { echo "no crontab for tester" >&2; exit 1; }; '
            'cat "$TABLE"; else cat > "$TABLE"; fi\n')
        (bin_dir / "crontab").chmod(0o755)
        home = self.root / "home"
        home.mkdir()
        environment = {**os.environ, "HOME": str(home), "TABLE": str(table), "TZ": "Asia/Tokyo",
                       "PATH": f"{bin_dir}:{os.environ['PATH']}"}
        environment.pop("AGENTRUN_TIMEZONE", None)

        def agentrun(*args, expected=0, **extra):
            result = subprocess.run([str(LAUNCHER), "history", *args], cwd=self.root, env={**environment, **extra},
                                    capture_output=True, text=True, timeout=30, check=False)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            return result.stdout + result.stderr

        self.assertIn("自動書き出しは登録されていません", agentrun("schedule"))
        table.write_text("15 3 * * * echo keep me\n")
        vault = self.root / "vault 100%"
        self.assertIn("毎日 04:00（Asia/Tokyo）に", agentrun("schedule", str(vault)))
        self.assertIn("前の登録は置き換えました", agentrun("schedule", str(vault), "--at", "4:30"))
        lines = table.read_text().splitlines()
        self.assertEqual(lines[0], "15 3 * * * echo keep me")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].startswith("30 4 * * * "), lines[1])
        self.assertIn("\\%", lines[1])  # cron would cut the command at a bare %
        self.assertIn("毎日 04:30（Asia/Tokyo）に " + str(vault), agentrun("schedule"))
        # A server clock in UTC gets the matching UTC time.
        self.assertIn("サーバーの時計では 19:30", agentrun("schedule", str(vault), "--at", "04:30", TZ="UTC"))
        self.assertTrue(table.read_text().splitlines()[1].startswith("30 19 * * * "))
        self.assertIn("--at は 04:00 のように", agentrun("schedule", str(vault), "--at", "25:00", expected=2))

        # Run the command exactly as cron would: through sh, with % restored by cron.
        self.archived_run("20261117_090000_assist_codex", [message("user", "夜間の書き出し確認"),
                                                           message("assistant", "了解")])
        command = table.read_text().splitlines()[1].split(None, 5)[5].replace("\\%", "%")
        cron = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TABLE": str(table)}
        subprocess.run(["sh", "-c", command], env=cron, cwd="/", timeout=60, check=True)
        self.assertTrue(any("夜間の書き出し確認" in path.read_text() for path in vault.glob("*.md")))
        status = json.loads((self.history_root / "auto-export.json").read_text())
        self.assertEqual(status["status"], "success")
        log = (self.history_root / "auto-export.log").read_text()
        self.assertIn("自動書き出しを始めます", log)
        self.assertIn("実行中のセッションはありません", log)
        self.assertNotIn("自動書き出しが失敗", self.history_cli("list"))

        # A failure is recorded and shown on the next list.
        shutil.rmtree(vault)
        vault.write_text("not a folder\n")
        failed = subprocess.run(["sh", "-c", command], env=cron, cwd="/", timeout=60, check=False)
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(json.loads((self.history_root / "auto-export.json").read_text())["status"], "failed")
        self.assertIn("[注意] 毎日の自動書き出しが失敗しました", self.history_cli("list"))
        self.assertIn("前回: 失敗", agentrun("schedule"))

        # A run still going when the next one starts is left to finish.
        import fcntl
        with (self.history_root / "auto-export.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            subprocess.run(["sh", "-c", command], env=cron, cwd="/", timeout=60, check=True)
        self.assertIn("前回の自動書き出しがまだ動いているので", (self.history_root / "auto-export.log").read_text())

        self.assertIn("解除しました", agentrun("schedule", "--off"))
        self.assertEqual(table.read_text(), "15 3 * * * echo keep me\n")
        self.assertIn("登録されていません", agentrun("schedule", "--off"))

    def test_clear_starts_a_new_conversation_with_its_own_note(self):
        self.initialize("claude")
        project = self.store / ".claude/projects/-workspace"
        first, second = "aaaa1111", "bbbb2222"

        def turn(session, kind, text, stamp, **extra):
            content = text if kind == "user" else [{"type": "text", "text": text}]
            return {"sessionId": session, "cwd": "/workspace", "type": kind, "uuid": f"{session}-{stamp}",
                    "timestamp": f"2026-11-20T{stamp}Z", "message": {"role": kind, "content": content}, **extra}

        vault = self.root / "vault"
        write_jsonl(project / f"{first}.jsonl", [turn(first, "user", "図を直して", "01:00:00"),
                                                 turn(first, "assistant", "図を直した", "01:01:00")])
        (self.run / "artifacts").mkdir()
        (self.run / "artifacts/run_title.txt").write_text("fixed the figure\n")
        collector.archive(self.run)
        self.history_cli("export-md", str(vault))
        next(vault.glob("*.md")).rename(vault / "図のメモ.md")  # renamed in Obsidian
        # /clear: a new session that begins with the command, with a subagent of its own.
        write_jsonl(project / f"{second}.jsonl", [
            turn(second, "user", "<command-name>/clear</command-name>\n<command-message>clear</command-message>",
                 "02:00:00"),
            turn(second, "user", "表を作って", "02:00:10"), turn(second, "assistant", "表を作った", "02:05:00")])
        write_jsonl(project / second / "subagents/agent-x1.jsonl", [
            turn(second, "user", "表のデータを探して", "02:01:00", isSidechain=True),
            turn(second, "assistant", "data.csv にあります", "02:02:00", isSidechain=True)])
        # A cross-review during the second conversation.
        write_jsonl(self.store / "reviewers/codex/.codex/sessions/rollout.jsonl", [
            {"type": "session_meta", "payload": {"id": ID}},
            {**message("user", "表の変更を監査して"), "timestamp": "2026-11-20T02:03:00Z"}])
        collector.archive(self.run)

        listing = self.history_cli("list")
        self.assertIn("最初の依頼: 図を直して", listing)
        self.assertIn("最初の依頼: 表を作って", listing)
        self.assertIn(f"ID: {self.run.name}~2", listing)
        self.assertIn("（/clear 後の 2 つ目の会話）", listing)
        self.assertIn("新規 1 件、更新 1 件", self.history_cli("export-md", str(vault)))
        old = (vault / "図のメモ.md").read_text()  # the note from before /clear stays the first conversation's
        new = (vault / "2026-11-20 1100 fixed the figure.md").read_text()  # the run's title goes to its last one
        self.assertIn("図を直した", old)
        self.assertNotIn("表を作って", old)
        self.assertIn('conversation_id: "aaaa1111"', old)
        for text in ("表を作った", "data.csv にあります", "表の変更を監査して", 'conversation_id: "bbbb2222"',
                     'date: "2026-11-20T11:00:00"'):
            self.assertIn(text, new)
        self.assertNotIn("図を直した", new)
        self.history_cli("rename", f"{self.run.name}~2", "表の作成")
        self.history_cli("export-md", str(vault))
        self.assertTrue((vault / "2026-11-20 1100 表の作成.md").is_file())
        self.assertTrue((vault / "図のメモ.md").is_file())
        # Losing the state file: each note is still found by its conversation.
        (vault / ".agentrun-export.json").unlink()
        self.assertIn("新規 0 件", self.history_cli("export-md", str(vault)))
        self.assertEqual(sorted(p.name for p in vault.glob("*.md")), ["2026-11-20 1100 表の作成.md", "図のメモ.md"])

    def test_codex_sessions_split_by_clear_but_resume_stays_one_conversation(self):
        self.codex([{"type": "session_meta", "payload": {"id": ID}},
                    {**message("user", "学習して"), "timestamp": "2026-11-20T01:00:00Z"}])
        collector.archive(self.run)
        # Resumed: Codex keeps writing the same session; then /clear starts another one.
        resumed = self.parent / "resumed-run"
        resumed.mkdir()
        sessions.init(resumed, "codex", str(self.root), "assist", self.run)
        write_jsonl(self.path, [{"type": "session_meta", "payload": {"id": ID}},
                                {**message("user", "学習して"), "timestamp": "2026-11-20T01:00:00Z"},
                                {**message("user", "続きを"), "timestamp": "2026-11-21T01:00:00Z"}])
        other = "22345678-1234-1234-1234-123456789abc"
        write_jsonl(self.store / ".codex/sessions/2026/11/21/rollout-new.jsonl", [
            {"type": "session_meta", "payload": {"id": other}},
            {**message("user", "別の話"), "timestamp": "2026-11-21T02:00:00Z"}])
        collector.archive(resumed)
        listing = self.history_cli("list")
        self.assertEqual(listing.count("最初の依頼:"), 2, listing)
        self.assertIn("（resume 1 回）", listing)  # the first conversation went on in the resumed run
        self.assertIn("ID: resumed-run~2", listing)  # the new conversation began in the resumed run

    def test_resumed_sessions_read_oldest_first_whatever_their_file_names(self):
        self.initialize("claude")
        project = self.store / ".claude/projects/-workspace"

        def session(name, request, answer, day):
            base = {"sessionId": name, "cwd": "/workspace"}
            write_jsonl(project / f"{name}.jsonl", [
                {**base, "type": "user", "uuid": f"{name}-u", "timestamp": f"2026-11-{day}T01:00:00Z",
                 "message": {"role": "user", "content": request}},
                {**base, "type": "assistant", "uuid": f"{name}-a", "timestamp": f"2026-11-{day}T01:05:00Z",
                 "message": {"role": "assistant", "content": [{"type": "text", "text": answer}]}}])

        # UUID file names sort the newest resume first, then the first resume, then the start.
        session("aaaa", "二回目の再開", "応答3", "12")
        session("bbbb", "一回目の再開", "応答2", "05")
        session("cccc", "最初の依頼です", "応答1", "01")
        write_jsonl(self.store / "reviewers/codex/.codex/sessions/rollout.jsonl", [
            {"type": "session_meta", "payload": {"id": ID}},
            {**message("user", "監査してください"), "timestamp": "2026-10-01T00:00:00Z"}])
        order = ["最初の依頼です", "一回目の再開", "二回目の再開", "監査してください"]

        # Archives saved before the fix kept file-name order; they are reordered when read.
        with patch.object(history_export, "chronological", lambda markdown: markdown):
            collector.archive(self.run)
        legacy = self.database_rows()[0][2]
        self.assertGreater(legacy.index("最初の依頼です"), legacy.index("二回目の再開"))
        self.assertIn("最初の依頼: 最初の依頼です", self.history_cli("list"))
        vault = self.root / "vault"
        self.history_cli("export-md", str(vault))
        note = next(vault.glob("*.md")).read_text()
        self.assertEqual(sorted(order, key=note.index), order)

        # New archives are written in time order.
        collector.archive(self.run)
        archived = self.markdown()
        self.assertEqual(sorted(order, key=archived.index), order)
        self.assertEqual(history_export.chronological(archived), archived)

        # A message line that looks like a section heading leaves the archive untouched.
        odd = "# Conversation archive\n\n## Session: b (worker, claude)\n\n### User · 2026-11-02T00:00:00Z\n\nlater\n" \
              "## Review: quoted\n\n## Session: a (worker, claude)\n\n### User · 2026-11-01T00:00:00Z\n\nearlier\n"
        self.assertEqual(history_export.chronological(odd), odd)

    def test_claude_results_subagents_and_spilled_output(self):
        self.initialize("claude")
        project = self.store / ".claude/projects/-workspace"
        output = project / ID / "tool-results/large.txt"
        output.parent.mkdir(parents=True)
        output.write_text("complete spilled output\n```\n" + "z" * 40000)
        self.path = project / f"{ID}.jsonl"
        base = {"sessionId": ID, "version": "2.fixture", "cwd": "/workspace"}
        write_jsonl(self.path, [
            {**base, "type": "user", "uuid": "u1", "message": {"role": "user", "content": "actual user request"}},
            {**base, "type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "CLAUDE THOUGHT"},
                {"type": "redacted_thinking", "data": "DO NOT EXPORT REDACTED"},
                {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {"command": "run experiment", "timeout": 1000}}]}},
            {**base, "type": "user", "uuid": "r1", "toolUseResult": {"stdout": "observed stdout", "stderr": "observed stderr", "interrupted": False},
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool-1", "is_error": False,
                "content": f"<persisted-output>\nFull output saved to: /home/sandbox/.claude/projects/-workspace/{ID}/tool-results/large.txt\n</persisted-output>"}]}},
            {**base, "type": "user", "toolUseResult": "Exit code 17", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tool-2", "is_error": True, "content": "Exit code 17\nfailed command"}]}},
            {"type": "api-request-blob", "message": {"role": "assistant", "content": "DO NOT EXPORT API BLOB"}},
            {**base, "type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "public answer"}]}},
        ])
        child = project / ID / "subagents/agent-child.jsonl"
        write_jsonl(child, [{**base, "type": "assistant", "agentId": "child", "isSidechain": True,
                           "message": {"role": "assistant", "content": [{"type": "text", "text": "child answer"}]}}])
        result = collector.archive(self.run)
        text = self.markdown()
        for value in ("actual user request", "run experiment", "observed stdout", "observed stderr", "Exit code 17",
                      "complete spilled output", "z" * 40000, "child answer", "public answer"):
            self.assertIn(value, text)
        self.assertNotIn("DO NOT EXPORT", text)
        self.assertIn("<summary>Thinking", text)
        self.assertIn("CLAUDE THOUGHT", text)
        self.assertEqual(text.count("### User"), 1)
        self.assertEqual(result["transcripts"], 2)
        self.assertFalse(result["warnings"])

    def test_companion_paths_cannot_read_unrelated_files(self):
        self.initialize("claude")
        forbidden = self.root / "unrelated.txt"
        forbidden.write_text("NEVER READ THIS")
        warnings = set()
        result = history_export.companion_output(str(forbidden), self.run, self.store, warnings)
        self.assertNotIn("NEVER READ THIS", result)
        self.assertTrue(warnings)
        persisted = self.run / "scratch/claude/full.txt"
        persisted.parent.mkdir(parents=True)
        persisted.write_text("persisted background output")
        self.assertEqual(history_export.companion_output("/scratch/claude/full.txt", self.run, self.store, set()),
                         "persisted background output")

    def test_torn_final_line_is_not_a_silent_loss_of_earlier_messages(self):
        self.codex()
        with self.path.open("a") as stream:
            stream.write('{"type":"response_item"')
        result = collector.archive(self.run)
        self.assertIn("first request", self.markdown())
        self.assertIn("incomplete final record", self.markdown())
        self.assertEqual(len(result["warnings"]), 1)

    def test_malformed_record_preserves_previous_archive_and_original_history(self):
        self.codex()
        collector.archive(self.run)
        original = self.markdown()
        with self.path.open("a") as stream:
            stream.write("INVALID JSON\n")
        with self.assertRaisesRegex(ValueError, "invalid JSONL"):
            collector.archive(self.run)
        self.assertEqual(self.markdown(), original)
        self.assertIn("INVALID JSON", self.path.read_text())
        self.assertEqual(self.database_rows()[0][2], original)

    def test_idempotent_export_resume_and_renamed_run(self):
        self.codex()
        collector.archive(self.run)
        original_path = self.database_rows()[0][1]
        renamed = self.run.with_name("first-run_human_title")
        self.run.rename(renamed)
        self.run = renamed
        collector.archive(self.run)
        self.assertEqual(len(self.database_rows()), 1)
        self.assertEqual(self.database_rows()[0][1], original_path)
        resumed = self.parent / "second-run"
        resumed.mkdir()
        sessions.init(resumed, "codex", str(self.root), "assist", self.run)
        with self.path.open("a") as stream:
            stream.write(json.dumps(message("assistant", "resumed answer")) + "\n")
        collector.archive(resumed)
        rows = {r[0]: r for r in self.database_rows()}
        self.assertEqual(len(rows), 2)
        self.assertNotIn("resumed answer", rows["first-run"][2])
        self.assertIn("resumed answer", rows["second-run"][2])
        self.assertEqual(json.loads(rows["second-run"][3])["parent_run_id"], "first-run")

    def test_empty_failed_start_is_archived_without_reading_home(self):
        self.initialize()
        credential = self.run / "home/.codex/auth.json"
        credential.write_text("DO NOT EXPORT CREDENTIAL")
        result = collector.archive(self.run)
        self.assertEqual(result["status"], "empty")
        self.assertNotIn("DO NOT EXPORT", self.markdown())
        self.assertTrue(credential.exists())

    def test_collector_waits_for_job_end_and_tolerates_query_failures(self):
        self.codex()
        control = collector.control_path(self.parent, self.data["run_id"])
        control.write_text(json.dumps({"origin_host": socket.gethostname(), "job_ref": "123"}))
        with patch.object(collector, "query_active", side_effect=[True, RuntimeError("temporary queue failure"), False, False]) as query, \
             patch.object(collector.time, "sleep"), contextlib.redirect_stderr(io.StringIO()):
            collector.watch(self.parent, self.data["run_id"])
        self.assertEqual(query.call_count, 4)
        self.assertEqual(json.loads(control.read_text())["status"], "archived")
        self.assertTrue((self.run / "live/history_export.json").exists())

    def test_queue_failures_alone_never_trigger_export(self):
        self.codex()
        control = collector.control_path(self.parent, self.data["run_id"])
        control.write_text(json.dumps({"origin_host": socket.gethostname(), "job_ref": "123"}))
        with patch.object(collector, "query_active", side_effect=[RuntimeError("unavailable"), KeyboardInterrupt]), \
             patch.object(collector.time, "sleep"), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            collector.watch(self.parent, self.data["run_id"])
        self.assertFalse((self.run / "live/history_export.json").exists())

    def test_collector_rejects_another_host(self):
        self.codex()
        control = collector.control_path(self.parent, self.data["run_id"])
        control.write_text(json.dumps({"origin_host": "another-host", "job_ref": "123"}))
        with self.assertRaisesRegex(ValueError, "original submission host"):
            collector.watch(self.parent, self.data["run_id"])

    def test_queue_query_and_accounting_fallback(self):
        completed = subprocess.CompletedProcess([], 0, "", "")
        invalid = subprocess.CompletedProcess([], 1, "", "invalid job id")
        accounting = subprocess.CompletedProcess([], 0, "123|TIMEOUT\n123.batch|FAILED\n", "")
        with patch.object(collector, "slurm_query", return_value=completed) as run:
            self.assertFalse(collector.query_active("123;cluster"))
            self.assertIn("cluster", run.call_args.args[0])
        with patch.object(collector, "slurm_query", side_effect=[invalid, accounting]), patch.object(collector.shutil, "which", return_value="/fake/sacct"):
            self.assertFalse(collector.query_active("123"))
        with patch.object(collector, "slurm_query", return_value=invalid), patch.object(collector.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "completion has not been established"):
                collector.query_active("123")

    def test_host_queue_filters_cannot_hide_an_active_batch_job(self):
        active = subprocess.CompletedProcess([], 0, "123\n", "")
        with patch.dict(os.environ, SQUEUE_PARTITION="unrelated", SQUEUE_STATES="pending"), \
             patch.object(collector, "slurm_query", return_value=active) as query:
            self.assertTrue(collector.query_active("123"))
        env = query.call_args.kwargs["env"]
        self.assertFalse(any(key.startswith("SQUEUE_") for key in env))
        self.assertEqual(env["LC_ALL"], "C")

    def test_suspended_jobs_are_active_and_retained_terminal_jobs_are_complete(self):
        for state, active in (('SUSPENDED', True), ('COMPLETING', True), ('RUNNING', True), ('TIMEOUT', False), ('COMPLETED', False)):
            with self.subTest(state=state), patch.object(collector, 'slurm_query', return_value=subprocess.CompletedProcess([], 0, '123|' + state + '\n', '')) as query:
                self.assertEqual(collector.query_active('123'), active)
                self.assertIn('--states=all', query.call_args.args[0])


    def test_query_returns_without_waiting_for_descendant_pipes(self):
        import time
        start = time.monotonic()
        result = collector.slurm_query([sys.executable, "-c",
            "import subprocess,sys; subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print('123')"], timeout=1)
        self.assertEqual(result.stdout.strip(), "123")
        self.assertLess(time.monotonic() - start, 2)


    def test_manual_cli_export_records_failure_and_can_retry(self):
        self.codex()
        with self.path.open("a") as stream:
            stream.write("INVALID JSON\n")
        result = subprocess.run([str(LAUNCHER), "history", self.data["run_id"]], cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(json.loads((self.run / "live/history_export.json").read_text())["status"], "failed")
        write_jsonl(self.path, [message("assistant", "retry succeeded")])
        result = subprocess.run([str(LAUNCHER), "history", str(self.run)], cwd=self.root,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("retry succeeded", self.markdown())
        self.assertEqual(len(self.database_rows()), 1)

    def test_submission_and_collector_start_failures_are_distinguished(self):
        self.codex()
        failure = subprocess.CompletedProcess([], 17, "", "submission failed")
        success = subprocess.CompletedProcess([], 0, "123\n", "")
        with patch.object(collector.shutil, "which", return_value="/fake/squeue"), \
             patch.object(collector, "slurm_query", return_value=failure), \
             patch.object(collector.subprocess, "Popen") as start, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "sbatch failed"):
                collector.submit(self.run)
            start.assert_not_called()
        with patch.object(collector.shutil, "which", return_value="/fake/squeue"), \
             patch.object(collector, "slurm_query", return_value=success), \
             patch.object(collector.subprocess, "Popen", side_effect=OSError("start failed")):
            with self.assertRaisesRegex(RuntimeError, "Job 123 was submitted"):
                collector.submit(self.run)
        control = collector.control_path(self.parent, self.data["run_id"])
        self.assertEqual(json.loads(control.read_text())["status"], "collector_start_failed")
        self.assertTrue(self.path.exists())

    def test_collector_failure_retains_sources_and_records_retryable_status(self):
        self.codex()
        with self.path.open("a") as stream:
            stream.write("INVALID JSON\n")
        control = collector.control_path(self.parent, self.data["run_id"])
        control.write_text(json.dumps({"origin_host": socket.gethostname(), "job_ref": "123"}))
        with patch.object(collector, "query_active", return_value=False), patch.object(collector.time, "sleep"):
            with self.assertRaisesRegex(ValueError, "invalid JSONL"):
                collector.watch(self.parent, self.data["run_id"])
        self.assertEqual(json.loads(control.read_text())["status"], "failed")
        self.assertEqual(json.loads((self.run / "live/history_export.json").read_text())["status"], "failed")
        self.assertTrue(self.path.exists())
        write_jsonl(self.path, [message("assistant", "collector retry succeeded")])
        with patch.object(collector, "query_active", return_value=False), patch.object(collector.time, "sleep"):
            collector.watch(self.parent, self.data["run_id"])
        status = json.loads(control.read_text())
        self.assertEqual(status["status"], "archived")
        self.assertNotIn("error", status)

    def test_actual_submit_script_cleans_compute_home_then_host_exports_renamed_run(self):
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        fake_apptainer = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['--version']:
    print('fake apptainer')
    sys.exit(0)
args = sys.argv[1:]
run = Path(next(args[i+1].split(':/runs:')[0] for i,a in enumerate(args[:-1]) if a == '--bind' and ':/runs:' in args[i+1]))
store = Path(next(args[i+1].split(':/home/sandbox/.codex/sessions:')[0] for i,a in enumerate(args[:-1]) if a == '--bind' and ':/home/sandbox/.codex/sessions:' in args[i+1]))
p = store / '2026/10/16/rollout.jsonl'
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps({'type':'session_meta','payload':{'id':'native-session','source':'exec','originator':'test-cli'}}) + '\n' + json.dumps({'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':'batch conversation persisted'}]}}) + '\n')
(run / 'artifacts/run_title.txt').write_text('batch archive title')
sys.exit(17)
'''
        fake_sbatch = r'''#!/usr/bin/env python3
import os, subprocess, sys
from pathlib import Path
assert sys.argv[1] == '--parsable'
assert '--nodes=1' in sys.argv and '--ntasks=1' in sys.argv
with Path(os.environ['TEST_COMPUTE_LOG']).open('w') as log:
    subprocess.run(['bash', sys.argv[-1]], env=dict(os.environ, SLURM_JOB_ID='123', SLURMD_NODENAME='fake-compute'), stdout=log, stderr=log)
print('123')
'''
        for name, text in (("apptainer", fake_apptainer), ("sbatch", fake_sbatch), ("squeue", "#!/bin/sh\nexit 0\n")):
            p = bin_dir / name
            p.write_text(text)
            p.chmod(0o755)
        home = self.root / "host-home"
        home.mkdir()
        env = dict(os.environ, HOME=str(home), PATH=f"{bin_dir}:{os.environ['PATH']}", TEST_COMPUTE_LOG=str(self.root / "compute.log"))
        env.pop("AGENTRUN_SECRETS_FILE", None)
        result = subprocess.run([str(LAUNCHER), "experiment", "--agent", "codex", "--submit", "--no-secrets", "task"],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr + (self.root / "compute.log").read_text())
        self.assertIn("バッチジョブを投入しました: job 123", result.stdout)
        pid = int(re.search(r"pid=(\d+)", result.stdout).group(1))
        def stop_collector():
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        self.addCleanup(stop_collector)
        run = (self.parent / "latest").resolve()
        self.assertTrue(run.name.endswith("batch-archive-title"))
        self.assertFalse((run / "home").exists())
        self.assertTrue((run / "live/session_finished.txt").exists())
        self.assertNotIn("history_tool", (run / "submit.sbatch").read_text())
        deadline = time.monotonic() + 8
        while not (run / "live/history_export.json").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((run / "live/history_export.json").exists(), result.stdout)
        control = next((self.history_root / "jobs").glob("*.json"))
        while json.loads(control.read_text())["status"] != "archived" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(json.loads(control.read_text())["status"], "archived")
        status = json.loads((run / "live/history_export.json").read_text())
        self.assertEqual(status["status"], "success", status)
        self.assertEqual(status["archive_host"], socket.gethostname())
        self.assertIn("batch conversation persisted", Path(status["markdown"]).read_text())
        self.assertEqual(sessions.manifest(run)["launcher_cwd"], str(self.root))
        self.assertEqual((run / "live/exit_code.txt").read_text().strip(), "17")
        self.assertEqual(json.loads((run / "live/status.json").read_text())["status"], "failed")
        with sqlite3.connect(self.history_root / "index.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM conversations").fetchone()[0], 1)


class ExampleTests(unittest.TestCase):
    def test_history_examples_match_the_current_format(self):
        examples = ROOT / "docs/history-examples"
        sys.path.insert(0, str(examples))
        try:
            import make_examples
        finally:
            sys.path.pop(0)
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ):
            fresh = make_examples.main(Path(temp))
            self.assertEqual(fresh, sorted(p.relative_to(examples).as_posix() for folder in ("archive", "obsidian")
                                           for p in (examples / folder).rglob("*") if p.is_file()))
            for name in fresh:
                self.assertEqual((Path(temp) / name).read_text(), (examples / name).read_text(),
                                 f"docs/history-examples/{name} is stale: run python3 docs/history-examples/make_examples.py")


if __name__ == "__main__":
    unittest.main()
