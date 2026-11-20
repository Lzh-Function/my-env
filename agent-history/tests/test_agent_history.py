"""agent-history against a fake home holding each CLI's native transcripts; no model is called."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLAUDE_ID = "11111111-1111-1111-1111-111111111111"
CODEX_ID = "019a0000-0000-7000-8000-000000000001"
AGY_ID = "22222222-2222-2222-2222-222222222222"


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))


class AgentHistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="agent history ")
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / "home"
        self.home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        self.env.update(HOME=str(self.home), PYTHONPATH=str(ROOT), AGENT_HISTORY_DIR=str(self.home / "agent-history"),
                        AGENT_HISTORY_TIMEZONE="Asia/Tokyo")
        self.claude = self.home / ".claude/projects/-work-paper" / f"{CLAUDE_ID}.jsonl"
        write_jsonl(self.claude, [
            {"type": "user", "uuid": "u1", "sessionId": CLAUDE_ID, "cwd": "/work/paper",
             "timestamp": "2026-11-20T01:00:00Z", "message": {"role": "user", "content": "図を直して"}},
            {"type": "assistant", "uuid": "a1", "sessionId": CLAUDE_ID, "timestamp": "2026-11-20T01:01:00Z",
             "message": {"role": "assistant", "content": [
                 {"type": "thinking", "thinking": "Claude の思考"},
                 {"type": "thinking", "thinking": "", "signature": "ENCRYPTED"},
                 {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "ls figures"}}]}},
            {"type": "user", "uuid": "r1", "sessionId": CLAUDE_ID, "timestamp": "2026-11-20T01:01:05Z",
             "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "fig1.png"}]}},
            {"type": "assistant", "uuid": "a2", "sessionId": CLAUDE_ID, "timestamp": "2026-11-20T01:02:00Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "直しました"}]}},
            {"type": "ai-title", "aiTitle": "図の修正", "sessionId": CLAUDE_ID},
        ])
        write_jsonl(self.claude.parent / CLAUDE_ID / "subagents/agent-a1.jsonl", [
            {"type": "user", "uuid": "s1", "timestamp": "2026-11-20T01:01:10Z",
             "message": {"role": "user", "content": "図を探して"}},
            {"type": "assistant", "uuid": "s2", "timestamp": "2026-11-20T01:01:20Z",
             "message": {"role": "assistant", "content": [{"type": "text", "text": "fig1.png です"}]}}])
        # A session that was opened and closed without asking anything.
        write_jsonl(self.claude.parent / "33333333-3333-3333-3333-333333333333.jsonl", [
            {"type": "user", "uuid": "x1", "cwd": "/work/paper", "timestamp": "2026-11-19T00:00:00Z",
             "message": {"role": "user", "content": "<command-name>/exit</command-name>\n<command-args></command-args>"}}])
        self.codex = self.home / f".codex/sessions/2026/11/20/rollout-2026-11-20T10-00-00-{CODEX_ID}.jsonl"
        write_jsonl(self.codex, [
            {"type": "session_meta", "timestamp": "2026-11-20T02:00:00Z",
             "payload": {"id": CODEX_ID, "cwd": "/work/model", "source": "cli", "creator_user_id": "PRIVATE"}},
            {"type": "response_item", "timestamp": "2026-11-20T02:00:01Z", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "学習を回して"}]}},
            {"type": "response_item", "timestamp": "2026-11-20T02:04:00Z", "payload": {
                "type": "reasoning", "summary": [{"type": "summary_text", "text": "Codex の要約された思考"}],
                "encrypted_content": "ENCRYPTED"}},
            {"type": "response_item", "timestamp": "2026-11-20T02:04:30Z", "payload": {
                "type": "reasoning", "summary": [], "encrypted_content": "ENCRYPTED"}},
            {"type": "response_item", "timestamp": "2026-11-20T02:05:00Z", "payload": {
                "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "回しました"}]}}])
        write_jsonl(self.home / ".codex/session_index.jsonl", [
            {"id": CODEX_ID, "thread_name": "古い名前"}, {"id": CODEX_ID, "thread_name": "学習の実行"}])
        agy = self.home / ".gemini/antigravity-cli"
        write_jsonl(agy / "brain" / AGY_ID / ".system_generated/logs/transcript_full.jsonl", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
             "created_at": "2026-11-20T03:00:00Z", "content": "<USER_REQUEST>\nREADME を書いて\n</USER_REQUEST>"},
            {"step_index": 1, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
             "created_at": "2026-11-20T03:01:00Z", "thinking": "agy の思考", "content": "書きました"}])
        write_jsonl(agy / "brain/44444444-4444-4444-4444-444444444444/.system_generated/logs/transcript.jsonl", [
            {"step_index": 0, "source": "SUBAGENT", "type": "USER_INPUT", "created_at": "2026-11-20T03:00:30Z",
             "content": "<USER_REQUEST>\nsubtask\n</USER_REQUEST>"}])
        (agy / "cache").mkdir(parents=True)
        (agy / "cache/conversation_metadata.json").write_text(json.dumps({"conversations": {AGY_ID: {"summary": {
            "Title": "README の作成", "WorkspaceURIs": ["file:///work/docs"]}}}}))

    def cli(self, *args, expected=0, stdin=None):
        result = subprocess.run([sys.executable, "-m", "agent_history", *map(str, args)], env=self.env, input=stdin,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def test_sync_archives_each_cli_once_and_only_again_when_changed(self):
        self.assertIn("新規 4 件、更新 0 件、変更なし 0 件", self.cli("sync"))
        self.assertIn("新規 0 件、更新 0 件、変更なし 4 件", self.cli("sync"))
        archive = (self.home / f"agent-history/archives/claude/{CLAUDE_ID}.md").read_text()
        self.assertIn(f"## Session: {CLAUDE_ID} (worker, claude)", archive)
        self.assertIn("## Session: agent-a1 (subagent, claude)", archive)
        self.assertIn("fig1.png", archive)
        # Thinking is archived as its own detail; encrypted or empty thinking leaves nothing behind.
        self.assertIn("<summary>Thinking · 2026-11-20T01:01:00Z</summary>", archive)
        self.assertIn("Claude の思考", archive)
        for provider, ident, text in (("codex", CODEX_ID, "Codex の要約された思考"), ("antigravity", AGY_ID, "agy の思考")):
            other = (self.home / f"agent-history/archives/{provider}/{ident}.md").read_text()
            self.assertIn(text, other)
            self.assertNotIn("ENCRYPTED", other)
            self.assertEqual(other.count("<summary>Thinking"), 1)
        self.assertNotIn("PRIVATE", (self.home / f"agent-history/archives/codex/{CODEX_ID}.md").read_text())
        self.assertFalse((self.home / "agent-history/archives/antigravity/44444444-4444-4444-4444-444444444444.md").exists())
        self.assertEqual((self.home / "agent-history/index.sqlite3").stat().st_mode & 0o777, 0o600)
        with self.codex.open("a") as stream:
            stream.write(json.dumps({"type": "response_item", "timestamp": "2026-11-20T03:00:00Z", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": "もう一度"}]}}) + "\n")
        self.assertIn("新規 0 件、更新 1 件、変更なし 3 件", self.cli("sync"))

    def test_list_search_hide_empty_sessions_and_export_notes(self):
        listing = self.cli("list")
        self.assertIn("claude  paper  図の修正", listing)
        self.assertIn("codex  model  学習の実行", listing)  # the newest thread name wins
        self.assertIn("antigravity  docs  README の作成", listing)
        self.assertIn("最初の依頼: README を書いて", listing)
        self.assertNotIn("33333333", listing)  # opened and closed without a request
        self.assertLess(listing.index("antigravity"), listing.index("codex"))  # most recently active first
        self.assertIn("学習の実行", self.cli("search", "回しました", "--agent", "codex"))
        self.assertIn("該当する会話はありません", self.cli("search", "回しました", "--agent", "claude"))
        vault = self.home / "vault"
        self.assertIn("新規 3 件", self.cli("export-md", vault))
        note = (vault / "2026-11-20 1000 図の修正.md").read_text()
        self.assertIn('agent: "claude"', note)
        self.assertIn('project: "/work/paper"', note)
        self.assertIn("tags: [agent-history]", note)
        self.assertIn("## サブエージェントのセッション（Claude）", note)
        self.assertIn("%% agent-history:begin tool %%", note)
        # Folded by default, with its own marker so it can be stripped apart from tool output.
        block = note[note.index("%% agent-history:begin thinking %%"):]
        self.assertIn("> [!abstract]- 💭 思考", block[:200])
        self.assertIn("Claude の思考", block[:300])
        stripped = subprocess.run(["sed", "/^%% agent-history:begin /,/^%% agent-history:end %%$/d"],
                                  input=note, capture_output=True, text=True).stdout
        self.assertNotIn("Claude の思考", stripped)
        self.assertIn("直しました", stripped)
        self.assertIn("変更なし 3 件", self.cli("export-md", vault))
        self.cli("rename", CLAUDE_ID[:8], "論文の図")
        self.assertIn("更新 1 件", self.cli("export-md", vault))
        self.assertTrue((vault / "2026-11-20 1000 論文の図.md").is_file())
        self.assertFalse((vault / "2026-11-20 1000 図の修正.md").exists())
        self.cli("rename", CLAUDE_ID, "--clear")
        self.assertIn("claude  paper  図の修正", self.cli("list"))
        result = subprocess.run([sys.executable, "-m", "agent_history", "rename", "zzz", "x"], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 2)
        self.assertIn("当たる会話がありません", result.stderr)

    def test_names_and_folders_written_after_the_turn_are_picked_up(self):
        self.cli("sync")
        # Codex names a thread a moment after the turn; the transcript itself does not change.
        with (self.home / ".codex/session_index.jsonl").open("a") as stream:
            stream.write(json.dumps({"id": CODEX_ID, "thread_name": "学習の再実行"}) + "\n")
        self.assertIn("更新 1 件", self.cli("sync"))
        self.assertIn("学習の再実行", self.cli("list", "--agent", "codex"))
        # agy may not have described a new conversation yet: the Stop hook's cwd, then agy's
        # record of the newest conversation per folder, fill in its folder.
        new = "55555555-5555-5555-5555-555555555555"
        log = self.home / ".gemini/antigravity-cli/brain" / new / ".system_generated/logs/transcript.jsonl"
        write_jsonl(log, [{"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT",
                           "created_at": "2026-11-20T05:00:00Z", "content": "<USER_REQUEST>\n表を作って\n</USER_REQUEST>"}])
        self.cli("hook", "antigravity", stdin=json.dumps({"conversationId": new, "cwd": "/work/tables",
                                                          "transcriptPath": str(log)}))
        archive = self.home / f"agent-history/archives/antigravity/{new}.md"
        deadline = time.monotonic() + 20
        while not archive.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.2)
        self.assertIn('"cwd": "/work/tables"', archive.read_text())
        other = "66666666-6666-6666-6666-666666666666"
        write_jsonl(self.home / ".gemini/antigravity-cli/brain" / other / ".system_generated/logs/transcript.jsonl", [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-20T06:00:00Z",
             "content": "<USER_REQUEST>\n図を作って\n</USER_REQUEST>"}])
        (self.home / ".gemini/antigravity-cli/cache/last_conversations.json").write_text(
            json.dumps({"/work/figures": other}))
        self.assertIn("antigravity  figures", self.cli("list", "--agent", "antigravity"))

    def archive_text(self, provider, ident):
        text = (self.home / f"agent-history/archives/{provider}/{ident}.md").read_text()
        return "\n".join(line for line in text.splitlines() if '"archived_at"' not in line)

    def assert_same_as_full_read(self):
        """The incremental archives equal what reading every file from the start gives."""
        incremental = {(p, i): self.archive_text(p, i) for p, i in self.ids}
        self.cli("sync", "--force")
        for key, text in incremental.items():
            self.assertEqual(text, self.archive_text(*key), key)

    def test_long_conversations_are_read_only_from_where_they_left_off(self):
        legacy_id = "019a0000-0000-7000-8000-000000000002"
        legacy = self.home / f".codex/sessions/2026/11/19/rollout-2026-11-19T10-00-00-{legacy_id}.jsonl"
        write_jsonl(legacy, [{"type": "session_meta", "payload": {"id": legacy_id, "cwd": "/work/old"}}])
        self.ids = [("claude", CLAUDE_ID), ("codex", CODEX_ID), ("antigravity", AGY_ID), ("codex", legacy_id)]
        agy_log = self.home / ".gemini/antigravity-cli/brain" / AGY_ID / ".system_generated/logs/transcript_full.jsonl"
        self.cli("sync")

        def append(path, *records):
            with path.open("a") as stream:
                stream.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in records)

        # A tool call in one read and its result in the next (Claude Code, Codex, agy).
        append(self.claude, {"type": "assistant", "uuid": "a3", "timestamp": "2026-11-20T05:00:00Z", "message": {
            "role": "assistant", "content": [{"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "x"}}]}})
        append(self.codex, {"type": "response_item", "timestamp": "2026-11-20T05:00:00Z", "payload": {
            "type": "function_call", "name": "exec_command", "call_id": "c2", "arguments": "{}"}})
        append(agy_log, {"step_index": 2, "type": "PLANNER_RESPONSE", "created_at": "2026-11-20T05:00:00Z",
                         "tool_calls": [{"name": "run_command", "args": {"CommandLine": "ls"}}]})
        # An old Codex log with messages only as events, first after other output.
        append(legacy, {"type": "response_item", "payload": {"type": "function_call", "name": "x", "call_id": "l1"}},
               {"type": "event_msg", "timestamp": "2026-11-19T01:00:00Z", "payload": {"type": "user_message", "message": "古い形式の依頼"}})
        self.cli("sync")
        append(self.claude, {"type": "user", "uuid": "r3", "timestamp": "2026-11-20T05:00:05Z", "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "contents"}]}})
        append(self.codex, {"type": "response_item", "timestamp": "2026-11-20T05:00:05Z", "payload": {
            "type": "function_call_output", "call_id": "c2", "output": "done"}})
        append(agy_log, {"step_index": 3, "type": "GENERIC", "created_at": "2026-11-20T05:00:05Z", "content": "listing"})
        append(legacy, {"type": "event_msg", "timestamp": "2026-11-19T01:01:00Z", "payload": {"type": "agent_message", "message": "古い形式の返答"}})
        # A line still being written is left for the next read.
        with self.claude.open("a") as stream:
            stream.write('{"type": "assistant", "uuid": "a4", "timestamp": "2026-11-20T05:01:00Z", "message": {"role": "assi')
        self.cli("sync")
        claude = self.archive_text("claude", CLAUDE_ID)
        self.assertIn("Tool result: Read · t2", claude)
        self.assertIn("Tool result: exec_command · c2", self.archive_text("codex", CODEX_ID))
        self.assertIn("Tool result: run_command · 3", self.archive_text("antigravity", AGY_ID))
        self.assertIn("古い形式の返答", self.archive_text("codex", legacy_id))
        with self.claude.open("a") as stream:
            stream.write('stant", "content": [{"type": "text", "text": "書き終わりました"}]}}\n')
        self.cli("sync")
        self.assertIn("書き終わりました", self.archive_text("claude", CLAUDE_ID))
        # Each file is read only from where the last read stopped.
        cache = self.home / "agent-history/cache" / f"claude-{CLAUDE_ID}"
        states = [json.loads(p.read_text()) for p in cache.glob("*.json")]
        self.assertIn(self.claude.stat().st_size, [state["offset"] for state in states])
        self.assert_same_as_full_read()
        # A rewritten file (agy rewrites its log when compacting) is read again from the start.
        write_jsonl(agy_log, [
            {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "created_at": "2026-11-20T03:00:00Z",
             "content": "<USER_REQUEST>\n要約後の依頼\n</USER_REQUEST>"}])
        self.cli("sync")
        agy = self.archive_text("antigravity", AGY_ID)
        self.assertIn("要約後の依頼", agy)
        self.assertNotIn("listing", agy)
        self.assert_same_as_full_read()

    def test_hooks_install_keeps_other_hooks_and_uninstall_removes_only_ours(self):
        other = {"type": "command", "command": "orca-hook.sh", "timeout": 10}
        claude_settings = self.home / ".claude/settings.json"
        claude_settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": [{"hooks": [other]}],
                                                                          "PreToolUse": [{"matcher": "*", "hooks": [other]}]}}))
        codex_hooks = self.home / ".codex/hooks.json"
        codex_hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [other]}]}}))
        agy_hooks = self.home / ".gemini/config/hooks.json"
        agy_hooks.parent.mkdir(parents=True)
        agy_hooks.write_text(json.dumps({"orca-status": {"Stop": [other]}}))
        before = {p: p.read_text() for p in (claude_settings, codex_hooks, agy_hooks)}
        for _ in range(2):  # installing twice leaves one entry
            self.cli("hooks", "install")
        claude = json.loads(claude_settings.read_text())
        self.assertEqual(claude["model"], "opus")
        self.assertEqual(claude["hooks"]["PreToolUse"], [{"matcher": "*", "hooks": [other]}])
        stop = claude["hooks"]["Stop"]
        self.assertEqual(stop[0], {"hooks": [other]})
        self.assertEqual(len(stop), 2)
        self.assertIn("-m agent_history hook claude", stop[1]["hooks"][0]["command"])
        codex = json.loads(codex_hooks.read_text())["hooks"]["Stop"]
        self.assertEqual((len(codex), codex[0]), (2, {"hooks": [other]}))
        agy = json.loads(agy_hooks.read_text())
        self.assertEqual(agy["orca-status"], {"Stop": [other]})
        self.assertIn("-m agent_history hook antigravity", agy["agent-history"]["Stop"][0]["command"])
        self.assertTrue(claude_settings.with_name("settings.json.agent-history.bak").is_file())
        self.assertEqual(self.cli("hooks", "status").count("登録済み"), 3)
        self.cli("hooks", "uninstall")
        for path, text in before.items():
            self.assertEqual(json.loads(path.read_text()), json.loads(text), path)
        self.assertEqual(self.cli("hooks", "status").count("未登録"), 3)

    def test_stop_hook_answers_at_once_and_archives_in_the_background(self):
        self.cli("sync")
        with self.claude.open("a") as stream:
            stream.write(json.dumps({"type": "user", "uuid": "u2", "timestamp": "2026-11-20T04:00:00Z",
                                     "message": {"role": "user", "content": "続きをお願い"}}) + "\n")
        for provider, payload in (("claude", {"session_id": CLAUDE_ID, "transcript_path": str(self.claude)}),
                                  ("codex", {"session_id": CODEX_ID, "transcript_path": None}),
                                  ("antigravity", {"conversationId": AGY_ID, "transcriptPath": str(
                                      self.home / ".gemini/antigravity-cli/brain" / AGY_ID
                                      / ".system_generated/logs/transcript_full.jsonl")})):
            started = time.monotonic()
            self.assertEqual(self.cli("hook", provider, stdin=json.dumps(payload)).strip(), "{}")
            self.assertLess(time.monotonic() - started, 5)
        archive = self.home / f"agent-history/archives/claude/{CLAUDE_ID}.md"
        deadline = time.monotonic() + 20
        while "続きをお願い" not in archive.read_text():
            self.assertLess(time.monotonic(), deadline, (self.home / "agent-history/hook.log").read_text())
            time.sleep(0.2)
        deadline = time.monotonic() + 20
        log = self.home / "agent-history/hook.log"
        while log.read_text().count(": ") < 3:
            self.assertLess(time.monotonic(), deadline, log.read_text())
            time.sleep(0.2)
        self.assertIn(f"claude {CLAUDE_ID}: updated", log.read_text())
        self.assertIn(f"codex {CODEX_ID}: same", log.read_text())  # found from its session ID alone
        # Broken input never fails the agent's turn.
        self.assertEqual(self.cli("hook", "claude", stdin="not json").strip(), "{}")


if __name__ == "__main__":
    unittest.main()
