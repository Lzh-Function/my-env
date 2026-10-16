"""セッション保存、末尾表示、native ID での再開のローカル回帰テスト。"""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shlex
import signal
import subprocess
import tempfile
import termios
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "runtime/agentrun/agentrun"
HELPER = ROOT / "runtime/agentrun/sessions.py"
SPEC = importlib.util.spec_from_file_location("sessions", HELPER)
sessions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sessions)
ID = "12345678-1234-1234-1234-123456789abc"


def write_jsonl(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))


def codex_history(store, ident=ID, text="修正しました"):
    path = store / f".codex/sessions/2026/10/08/rollout-{ident}.jsonl"
    write_jsonl(path, [
        {"type": "session_meta", "payload": {"id": ident}},
        {"type": "response_item", "payload": {"type": "message", "role": "developer",
                                               "content": [{"type": "input_text", "text": "HIDDEN POLICY"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
                                               "content": [{"type": "input_text", "text": "バグを修正して"}]}},
        {"type": "event_msg", "payload": {"type": "agent_message", "message": text}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "channel": "analysis",
                                               "content": [{"type": "output_text", "text": "HIDDEN THOUGHT"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                               "content": [{"type": "output_text", "text": text}]}},
    ])
    return path


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agentrun-sessions-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / ".agent-runs"
        self.parent.mkdir()

    def new_run(self, agent="codex", name="test-run"):
        run = self.parent / name
        run.mkdir()
        sessions.init(run, agent, str(self.root), "assist")
        data = sessions.manifest(run)
        return run, sessions.state_dir(run, data)

    def cli(self, *args, expected=0):
        result = subprocess.run(["python3", str(HELPER), *map(str, args)],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_live_history_survives_without_exit_cleanup(self):
        run, store = self.new_run()
        path = codex_history(store)
        with path.open("a") as stream:
            stream.write('{"type":"response_item","payload":')
        # finalize 未実行でも、既に書かれた会話を検索・表示できる。
        output = self.cli("preview", run).stdout
        self.assertIn("修正しました", output)
        self.assertNotIn("HIDDEN POLICY", output)
        self.assertNotIn("HIDDEN THOUGHT", output)
        self.assertEqual(output.count("[assistant]"), 1)
        self.assertEqual(sessions.discover(run, sessions.manifest(run))["id"], ID)

    def test_resume_pins_source_id_and_shares_only_state(self):
        run, store = self.new_run()
        codex_history(store)
        credential = run / "home/.codex/auth.json"
        credential.write_text("secret")
        resumed = self.parent / "resume-run"
        resumed.mkdir()
        sessions.init(resumed, "codex", str(self.root), "assist", run)
        self.assertEqual(sessions.manifest(run)["native_id"], ID)
        data = sessions.manifest(resumed)
        self.assertEqual(sessions.state_dir(resumed, data), store)
        self.assertEqual(data["parent_run_id"], "test-run")
        self.assertFalse(any(p.name == "auth.json" for p in store.rglob("*")))
        argv = shlex.split(sessions.command(resumed))[3:]
        self.assertEqual(argv[:3], ["codex", "resume", ID])
        self.assertNotIn("/runs/prompt.txt", argv)
        self.assertIn('sqlite_home="/home/sandbox/.codex/sqlite"', argv)
        # 続行中に /new した場合も、元 run の会話 ID は変えない。
        other = "22345678-1234-1234-1234-123456789abc"
        codex_history(store, other, "別の会話")
        self.cli("finalize", resumed)
        self.assertEqual(sessions.manifest(resumed)["native_id"], other)
        self.assertEqual(sessions.discover(run, sessions.manifest(run))["id"], ID)

    def test_claude_text_only_not_tools_or_thinking(self):
        run, store = self.new_run("claude")
        path = store / f".claude/projects/-workspace/{ID}.jsonl"
        write_jsonl(path, [
            {"type": "user", "sessionId": ID, "message": {"role": "user", "content": "続きを頼む"}},
            {"type": "assistant", "sessionId": ID, "message": {"role": "assistant", "content": [
                {"type": "thinking", "thinking": "HIDDEN THOUGHT"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "HIDDEN TOOL"}},
                {"type": "text", "text": "修正済みです"}]}},
            {"type": "user", "sessionId": ID, "message": {"role": "user", "content": [
                {"type": "tool_result", "content": "HIDDEN RESULT"}]}},
        ])
        self.cli("finalize", run)
        output = self.cli("preview", run).stdout
        self.assertIn("修正済みです", output)
        self.assertNotIn("HIDDEN", output)
        self.assertIn("claude --resume " + ID, sessions.command(run))

    def test_unsupported_agent_state_is_rejected_without_breaking_listing(self):
        run, store = self.new_run()
        codex_history(store)
        unsupported = self.parent / "unsupported-run"
        unsupported.mkdir()
        with self.assertRaisesRegex(ValueError, "Unsupported agent"):
            sessions.init(unsupported, "unsupported", str(self.root), "assist")
        self.assertFalse((unsupported / "session.json").exists())
        data = sessions.manifest(run)
        data.update(agent="unsupported", run_id=unsupported.name)
        sessions.save(unsupported, data)
        result = self.cli("list", self.parent)
        self.assertIn("unsupported-run", result.stdout)
        self.assertIn("test-run  codex", result.stdout)
        self.cli("fields", unsupported, expected=2)
        self.cli("command", unsupported, expected=2)

    def test_session_command_rejects_mismatched_cli(self):
        run, store = self.new_run()
        data = sessions.manifest(run)
        data.update(native_id=ID, native_cli="unsupported")
        sessions.save(run, data)
        self.cli("command", run, expected=2)

    def test_old_and_corrupt_runs_do_not_break_listing(self):
        old = self.parent / "old-run"
        old.mkdir()
        run, store = self.new_run()
        codex_history(store, text="最後\x1b[31m\x07\u009bの発言")
        bad = self.parent / "broken-run"
        bad.mkdir()
        (bad / "session.json").write_text("[]")
        listing = self.cli("list", self.parent).stdout
        self.assertIn("old-run", listing)
        self.assertIn("broken-run", listing)
        self.assertIn("test-run", listing)
        self.assertNotIn(".sessions", listing)
        for control in ("\x1b", "\x07", "\u009b"):
            self.assertNotIn(control, listing)
        self.cli("fields", old, expected=2)
        self.cli("pick", self.parent, expected=2)

    def test_renamed_run_resolves_original_id(self):
        run, store = self.new_run()
        codex_history(store)
        renamed = run.with_name(run.name + "_title")
        run.rename(renamed)
        self.assertEqual(self.cli("resolve", self.parent, "test-run").stdout.strip(), str(renamed))
        self.assertIn("再開可能", self.cli("preview", renamed).stdout)

    def test_picker_displays_id_and_snippet_and_accepts_id(self):
        run, store = self.new_run()
        codex_history(store)
        (self.parent / "old-run").mkdir()
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(["python3", str(HELPER), "pick", str(self.parent)],
                                    stdin=slave, stdout=subprocess.PIPE, stderr=slave)
            output = bytearray()
            deadline = time.monotonic() + 5
            while "番号または".encode() not in output:
                if time.monotonic() > deadline or proc.poll() is not None:
                    proc.kill()
                    proc.communicate()
                    self.fail(repr(output))
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
            shown = output.decode()
            self.assertIn("test-run", shown)
            self.assertIn("assistant: 修正しました", shown)
            self.assertNotIn("old-run", shown)
            os.write(master, b"test-run\n")
            selected, _ = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(selected.decode().strip(), str(run))
        finally:
            os.close(master)
            os.close(slave)

    def test_dry_run_includes_storage_without_creating_directories(self):
        result = subprocess.run([str(LAUNCHER), "dry-run", "assist", "--agent", "codex"],
                                cwd=self.root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(".sessions/", result.stdout)
        self.assertIn("/home/sandbox/.codex/sqlite", result.stdout)
        self.assertFalse(any(self.parent.iterdir()))

    def test_history_larger_than_tail_window(self):
        run, store = self.new_run()
        path = codex_history(store)
        with path.open("a") as stream:
            stream.write(json.dumps({"type": "tool_result", "data": "x" * 500000}) + "\n")
            stream.write(json.dumps({"type": "response_item", "payload": {"role": "assistant",
                                     "content": [{"type": "output_text", "text": "大きな履歴の末尾"}]}}) + "\n")
        self.assertIn("大きな履歴の末尾", self.cli("preview", run).stdout)


MOCK_SRUN = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shlex
import sys

run = Path(sys.argv[-1]).parent
args = shlex.split((run / "apptainer_exec.sh").read_text().splitlines()[-1])
store = next(Path(args[i+1].split(":/home/sandbox/.codex/sessions:")[0])
             for i, a in enumerate(args[:-1]) if a == "--bind" and
             ":/home/sandbox/.codex/sessions:" in args[i+1])
ident = "12345678-1234-1234-1234-123456789abc"
if os.environ["TEST_RESUME_STEP"] == "resume":
    command = args[-1]
    assert "codex resume " + ident in command, command
    assert "cat /runs/prompt.txt" not in command
    assert "--time=02:00:00" in sys.argv
    assert "--mem=12000M" in sys.argv
    assert "--cpus-per-task=2" in sys.argv
else:
    path = store / "2026/10/08/rollout.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type":"session_meta", "payload":{"id":ident}}) + "\n" +
                    json.dumps({"type":"response_item", "payload":{"role":"assistant",
                    "content":[{"type":"output_text", "text":"saved before kill"}]}}) + "\n")
    (run / "live/stdout.log").write_text("original logs")
    print("srun: TIME LIMIT", file=sys.stderr)
    sys.exit(1)
'''


class ResumeIntegrationTests(unittest.TestCase):
    def test_time_limit_then_resume_uses_saved_id_and_fresh_job(self):
        with tempfile.TemporaryDirectory(prefix="resume repo with spaces ") as temp:
            root = Path(temp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            mock = bin_dir / "srun"
            mock.write_text(MOCK_SRUN)
            mock.chmod(0o755)
            master, slave = pty.openpty()
            try:
                def controlling_terminal():
                    os.setsid()
                    fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                def execute(args, step):
                    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", TEST_RESUME_STEP=step)
                    proc = subprocess.Popen([str(LAUNCHER), *args], cwd=root, env=env,
                                            stdin=slave, stdout=slave, stderr=slave,
                                            preexec_fn=controlling_terminal)
                    output = bytearray()
                    deadline = time.monotonic() + 10
                    while proc.poll() is None:
                        if time.monotonic() > deadline:
                            os.killpg(proc.pid, signal.SIGKILL)
                            proc.wait()
                            self.fail(repr(output))
                        if select.select([master], [], [], 0.05)[0]:
                            output.extend(os.read(master, 65536))
                    while select.select([master], [], [], 0)[0]:
                        output.extend(os.read(master, 65536))
                    return proc.returncode, output.decode(errors="replace")

                before = termios.tcgetattr(slave)
                rc, output = execute(["assist", "--agent", "codex"], "initial")
                self.assertEqual(rc, 1, output)
                original = (root / ".agent-runs/latest").resolve()
                self.assertFalse((original / "home").exists())
                preview = subprocess.run([str(LAUNCHER), "resume", original.name, "--preview"],
                                         cwd=root, capture_output=True, text=True)
                self.assertEqual(preview.returncode, 0, preview.stderr)
                self.assertIn("saved before kill", preview.stdout)
                rc, output = execute(["resume", original.name, "--time", "02:00:00",
                                      "--mem", "12000M", "--cpus", "2"], "resume")
                self.assertEqual(rc, 0, output)
                resumed = (root / ".agent-runs/latest").resolve()
                self.assertNotEqual(resumed, original)
                self.assertEqual((original / "live/stdout.log").read_text(), "original logs")
                self.assertFalse((resumed / "home").exists())
                self.assertEqual(sessions.manifest(resumed)["native_id"], ID)
                self.assertEqual(termios.tcgetattr(slave), before)
            finally:
                os.close(master)
                os.close(slave)


if __name__ == "__main__":
    unittest.main()
