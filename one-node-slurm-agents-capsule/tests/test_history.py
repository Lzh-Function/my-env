"""Conversation export and host-only batch collection with synthetic transcripts."""

import contextlib
import io
import json
import os
import re
import signal
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
        return (self.run / "artifacts/conversation.md").read_text()

    def database_rows(self):
        with sqlite3.connect(self.parent / ".history/index.sqlite3") as db:
            return db.execute("SELECT run_id, markdown_path, markdown, metadata_json FROM conversations").fetchall()

    def test_codex_full_transcript_commands_and_optional_fields(self):
        self.codex([
            {"type": "session_meta", "payload": {"id": ID, "source": {"subagent": {"other": "guardian"}},
             "originator": "fixture", "cli_version": "0.test", "base_instructions": "DO NOT EXPORT POLICY"}},
            message("user", "first request"),
            message("developer", "DO NOT EXPORT POLICY"),
            message("assistant", "DO NOT EXPORT REASONING", phase="analysis"),
            {"type": "response_item", "payload": {"type": "reasoning", "encrypted_content": "DO NOT EXPORT REASONING"}},
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
        self.assertEqual((self.parent / ".history/index.sqlite3").stat().st_mode & 0o777, 0o600)

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
                {"type": "thinking", "thinking": "DO NOT EXPORT THOUGHT"},
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
        self.assertFalse((self.run / "artifacts/conversation.md").exists())

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
        with patch.object(collector.subprocess, "run", return_value=completed) as run:
            self.assertFalse(collector.query_active("123;cluster"))
            self.assertIn("cluster", run.call_args.args[0])
        with patch.object(collector.subprocess, "run", side_effect=[invalid, accounting]), patch.object(collector.shutil, "which", return_value="/fake/sacct"):
            self.assertFalse(collector.query_active("123"))
        with patch.object(collector.subprocess, "run", return_value=invalid), patch.object(collector.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "completion has not been established"):
                collector.query_active("123")

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
             patch.object(collector.subprocess, "run", return_value=failure), \
             patch.object(collector.subprocess, "Popen") as start, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "sbatch failed"):
                collector.submit(self.run)
            start.assert_not_called()
        with patch.object(collector.shutil, "which", return_value="/fake/squeue"), \
             patch.object(collector.subprocess, "run", return_value=success), \
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
with Path(os.environ['TEST_COMPUTE_LOG']).open('w') as log:
    subprocess.run(['bash', sys.argv[2]], env=dict(os.environ, SLURM_JOB_ID='123', SLURMD_NODENAME='fake-compute'), stdout=log, stderr=log)
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
        self.assertIn("Submitted batch job 123", result.stdout)
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
        control = next((self.parent / ".history/jobs").glob("*.json"))
        while json.loads(control.read_text())["status"] != "archived" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(json.loads(control.read_text())["status"], "archived")
        status = json.loads((run / "live/history_export.json").read_text())
        self.assertEqual(status["status"], "success", status)
        self.assertEqual(status["archive_host"], socket.gethostname())
        self.assertIn("batch conversation persisted", (run / "artifacts/conversation.md").read_text())
        self.assertEqual((run / "live/exit_code.txt").read_text().strip(), "17")
        self.assertEqual(json.loads((run / "live/status.json").read_text())["status"], "failed")
        with sqlite3.connect(self.parent / ".history/index.sqlite3") as db:
            self.assertEqual(db.execute("SELECT count(*) FROM conversations").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
