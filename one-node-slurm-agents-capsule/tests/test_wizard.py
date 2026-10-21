"""wizard の再開導線を PTY と mock srun で検証する。"""

import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import signal
import shlex
import struct
import subprocess
import tempfile
import termios
import time
import unittest

from test_sessions import LAUNCHER, MOCK_SRUN, codex_history, sessions


MOCK_GUM = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args[0] == "input" and os.environ.get("TEST_GUM_CANCEL_HEADER") and args[args.index("--header")+1].startswith(os.environ["TEST_GUM_CANCEL_HEADER"]):
    sys.exit(130)
with Path(os.environ["TEST_GUM_LOG"]).open("a") as stream:
    stream.write(json.dumps(args, ensure_ascii=False) + "\n")
if args[0] == "choose":
    header = args[args.index("--header") + 1]
    choices = args[args.index("--header") + 2:]
    print("resume" if header == "Select run mode" else choices[0])
elif args[0] == "input":
    print(args[args.index("--value") + 1])
elif args[0] == "confirm":
    sys.exit(1 if "--default=false" in args else 0)
'''


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wizard repo with spaces ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.parent = self.root / ".agent-runs"
        self.parent.mkdir()
        run = self.parent / "wizard-run"
        run.mkdir()
        sessions.init(run, "codex", str(self.root), "assist")
        codex_history(sessions.state_dir(run, sessions.manifest(run)), text="wizard の最後の発言")
        self.original = run.with_name("wizard-run_title")
        run.rename(self.original)
        (self.original / "original.log").write_text("keep original logs")
        (self.parent / "old-run").mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        srun = self.bin / "srun"
        srun.write_text(MOCK_SRUN)
        srun.chmod(0o755)
        host_home = self.root / "host-home"
        host_home.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", HOME=str(host_home),
                        AGENTRUN_HISTORY_DIR=str(self.root / "central-history"),
                        WIZARD_UI="plain", TEST_RESUME_STEP="resume", TERM="dumb", INPUTRC="/dev/null")
        self.args = ["wizard", "--agent", "claude", "--time", "02:00:00",
                     "--mem", "12000M", "--cpus", "2"]

    def execute(self, args, answers="", env=None, command=None, columns=80, clear_default=True):
        master, slave = pty.openpty()
        proc = None
        try:
            def controlling_terminal():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, columns, 0, 0))
            before = termios.tcgetattr(slave)
            proc = subprocess.Popen(command or [str(LAUNCHER), *args], cwd=self.root, env=env or self.env,
                                    stdin=slave, stdout=slave, stderr=slave, preexec_fn=controlling_terminal)
            replies = answers.splitlines()
            sent = 0
            # Input headings are emitted once per field. Readline may redraw
            # "> " repeatedly or hide it when a long default scrolls sideways.
            prompts = re.compile(
                rb'\x1b\[1;36m[^\r\n]*:cancel=[^\r\n]*\x1b\[0m\r?\n'
                rb'|#\? \(Enter=1, :back, :cancel\) |\(:back, :cancel\): '
            )
            output = bytearray()
            deadline = time.monotonic() + 10
            while proc.poll() is None:
                if time.monotonic() > deadline:
                    self.fail(f"Sent {sent}/{len(replies)} replies: {output!r}")
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
                matches = list(prompts.finditer(output))
                if sent < len(matches) and sent < len(replies):
                    # Wait until Readline has disabled canonical input. Sending
                    # Ctrl+U earlier lets the terminal consume it before the
                    # editable default exists, so the answer gets appended.
                    if termios.tcgetattr(slave)[3] & termios.ICANON:
                        continue
                    reply = replies[sent].encode()
                    if reply and clear_default:
                        reply = b'\x15' + reply
                    os.write(master, reply + b'\n')
                    sent += 1
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))
            self.assertEqual(termios.tcgetattr(slave), before)
            self.assertEqual(sent, len(replies), output.decode(errors="replace"))
            return proc.returncode, output.decode(errors="replace")
        finally:
            if proc is not None and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            os.close(master)
            os.close(slave)

    def test_plain_resume_picker_preview_resources_and_launch(self):
        extra = self.root / "extra mount"
        extra.mkdir()
        # mode=resume, run=1, preview=yes, defaults, add a bind, launch=yes
        answers = f"6\n1\ny\n\n\n\ny\n{extra}\n/extra:ro\nn\ny\n"
        rc, output = self.execute(self.args, answers)
        self.assertEqual(rc, 0, output)
        self.assertIn("wizard-run  codex", output)
        self.assertIn("[assistant]", output)
        self.assertIn("wizard の最後の発言", output)
        self.assertNotIn("old-run", output)
        resumed = (self.parent / "latest").resolve()
        self.assertNotEqual(resumed, self.original)
        self.assertEqual(sessions.manifest(resumed)["parent_run_id"], "wizard-run")
        self.assertEqual(sessions.manifest(resumed)["agent"], "codex")
        self.assertFalse((resumed / "home").exists())
        self.assertIn("/extra:ro", (resumed / "apptainer_exec.sh").read_text())
        self.assertEqual((self.original / "original.log").read_text(), "keep original logs")

    def test_bind_source_tab_completion_keeps_spaces_in_path(self):
        extra = self.root / "extra mount"
        extra.mkdir()
        answers = "6\n1\nn\n\n\n\ny\nextr\t\n/extra:ro\nn\ny\n"
        rc, output = self.execute(self.args, answers)
        self.assertEqual(rc, 0, output)
        self.assertIn("Tab=パス補完", output)
        generated = (self.parent / "latest/apptainer_exec.sh").read_text()
        self.assertIn(f"{extra}:/extra:ro", shlex.split(generated.splitlines()[-1]))

    def test_path_input_completion_in_all_ui_backends(self):
        extra = self.root / "unique space [literal] $(touch injected)"
        extra.mkdir()
        script = 'source "$1"; trap "exit 130" INT TERM; value="$(wizard_path_input "Host path" "")"; printf "PATH_VALUE=<%s>\\n" "$value"'
        for ui in ("plain", "gum", "whiptail", "dialog"):
            with self.subTest(ui=ui):
                rc, output = self.execute([], "uni\t\n", env=dict(self.env, WIZARD_UI=ui),
                                          command=["bash", "-c", script, "bash", str(LAUNCHER)])
                self.assertEqual(rc, 0, output)
                self.assertIn(f"PATH_VALUE=<{extra.name}/>", output)
                self.assertIn(":back=戻る", output)
                self.assertIn(":cancel=キャンセル", output)
        self.assertFalse((self.root / "injected").exists())

    def test_path_input_back_cancel_and_tilde(self):
        extra = Path(self.env["HOME"]) / "unique home"
        extra.mkdir()
        script = 'source "$1"; trap "exit 130" INT TERM; value="$(wizard_path_input "Host path" "")"; printf "PATH_VALUE=<%s>\\n" "$value"'
        command = ["bash", "-c", script, "bash", str(LAUNCHER)]
        rc, output = self.execute([], "~/uni\t\n", command=command)
        self.assertEqual(rc, 0, output)
        self.assertIn(f"PATH_VALUE=<{extra}/>", output)
        for answer, expected in ((":back\n", 10), (":cancel\n", 130), ("\x1b\n", 130), ("\x04\n", 130), ("\x03\n", 130)):
            with self.subTest(answer=repr(answer)):
                rc, output = self.execute([], answer, command=command)
                self.assertEqual(rc, expected, output)

    def test_path_input_keeps_prefilled_and_raw_special_paths(self):
        path = self.root / "space 'quote' \\slash $(touch injected)"
        path.mkdir()
        script = 'source "$1"; value="$(wizard_path_input "Host path" "$2")"; printf "PATH_VALUE=<%s>\\n" "$value"'
        command = ["bash", "-c", script, "bash", str(LAUNCHER), str(path)]
        for terminal in ("dumb", "xterm-256color"):
            for columns in (24, 80, 240):
                for answer in ("\n", f"{path}\n"):
                    with self.subTest(terminal=terminal, columns=columns, answer=answer):
                        rc, output = self.execute([], answer, command=command, columns=columns,
                                                  env=dict(self.env, TERM=terminal))
                        self.assertEqual(rc, 0, output)
                        self.assertIn(f"PATH_VALUE=<{path}>", output)
        self.assertFalse((self.root / "injected").exists())

    def test_path_navigation_shortcuts_work_with_prefilled_value(self):
        script = 'source "$1"; value="$(wizard_path_input "Host path" "$2")"; printf "%s\\n" "$value"'
        command = ["bash", "-c", script, "bash", str(LAUNCHER), str(self.root)]
        for ui in ("plain", "gum", "whiptail", "dialog"):
            for key, expected in (("\x1b[1;3D\n", 10), ("\x07\n", 130), ("\x1b\n", 130)):
                with self.subTest(ui=ui, key=repr(key)):
                    rc, output = self.execute([], key, command=command,
                                              env=dict(self.env, WIZARD_UI=ui), clear_default=False)
                    self.assertEqual(rc, expected, output)

    def test_declining_resume_creates_nothing(self):
        before = (self.original / "session.json").read_text()
        rc, output = self.execute(self.args, "6\n1\nn\n\n\n\nn\nn\n")
        self.assertEqual(rc, 0, output)
        self.assertIn("aborted", output)
        self.assertFalse((self.parent / "latest").exists())
        self.assertEqual((self.original / "session.json").read_text(), before)
        self.assertEqual(len(list(self.parent.glob("*_resume-*"))), 0)

    def test_no_ready_sessions_returns_reason_without_launch(self):
        store = sessions.state_dir(self.original, sessions.manifest(self.original))
        for path in store.rglob("*.jsonl"):
            path.unlink()
        rc, output = self.execute(self.args, "6\n")
        self.assertEqual(rc, 2, output)
        self.assertIn("再開可能な run がありません", output)
        self.assertFalse((self.parent / "latest").exists())

    def test_new_assist_flow_still_dispatches_normally(self):
        # 最後の起動処理だけを stub にして既存の新規 run 導線を検証する。
        script = 'source "$1"; command_prepare() { printf "PREPARE_MODE=%s\\n" "$1"; }; command_wizard'
        rc, output = self.execute([], "1\n1\n1\n\n\n\n\n\n\nn\nn\nn\n\ny\n",
                                  command=["bash", "-c", script, "bash", str(LAUNCHER)])
        self.assertEqual(rc, 0, output)
        self.assertIn("PREPARE_MODE=assist", output)
        self.assertNotIn("再開対象", output)

    def test_gum_backend_uses_same_ready_choices(self):
        gum = self.bin / "gum"
        gum.write_text(MOCK_GUM)
        gum.chmod(0o755)
        log = self.root / "gum.jsonl"
        env = dict(self.env, WIZARD_UI="gum", TEST_GUM_LOG=str(log))
        rc, output = self.execute(self.args, env=env)
        self.assertEqual(rc, 0, output)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        menus = [call for call in calls if call[0] == "choose"]
        self.assertIn("resume", menus[0])
        self.assertIn("wizard-run  codex", menus[1][3])
        self.assertIn("assistant: wizard の最後の発言", menus[1][3])
        self.assertNotIn("old-run", str(menus))
        self.assertFalse((self.parent / "latest/home").exists())

    def test_back_from_resource_keeps_editable_values(self):
        answers = "6\n1\nn\n16000M\n:back\n12000M\n\n\nn\ny\n"
        rc, output = self.execute(self.args, answers)
        self.assertEqual(rc, 0, output)
        self.assertIn("> 16000M", output)
        self.assertIn("--mem 12000M", output)

    def test_back_from_agent_keeps_selected_default(self):
        script = 'source "$1"; command_prepare() { printf "PREPARE_AGENT=%s\\n" "$AGENT"; }; command_wizard --agent codex'
        answers = "1\n:back\n1\n\n1\n\n\n\n\n\n\nn\nn\nn\n\ny\n"
        rc, output = self.execute([], answers, command=["bash", "-c", script, "bash", str(LAUNCHER)])
        self.assertEqual(rc, 0, output)
        self.assertIn("PREPARE_AGENT=codex", output)

    def test_stale_agent_defaults_reset_to_claude_and_clear_reviewer_lists(self):
        state_file = Path(self.env["HOME"]) / ".agentrun/wizard-last"
        state_file.parent.mkdir()
        state_file.write_text(json.dumps({"cwd": str(self.root), "agent": "unsupported",
                                          "agents": "claude,unsupported", "reviewers": "unsupported"}))
        script = 'source "$1"; command_prepare() { printf "SELECTED=%s AGENTS=%s REVIEWERS=%s\\n" "$AGENT" "$REQUESTED_AGENTS" "$REVIEWERS"; }; command_wizard'
        answers = "1\n1\n1\n\n\n\n\n\n\nn\nn\nn\n\ny\n"
        rc, output = self.execute([], answers, command=["bash", "-c", script, "bash", str(LAUNCHER)])
        self.assertEqual(rc, 0, output)
        self.assertIn("SELECTED=claude AGENTS= REVIEWERS=", output)
        self.assertNotIn("unsupported", output)
        menu = output.split("Select agent", 1)[1].split("Select launch style", 1)[0]
        self.assertIn("1) claude", menu)
        self.assertIn("2) codex", menu)
        self.assertIn("3) ← 戻る", menu)

    def test_explicit_resources_override_previous_defaults(self):
        state_file = Path(self.env["HOME"]) / ".agentrun/wizard-last"
        state_file.parent.mkdir()
        state_file.write_text(json.dumps({"cwd": str(self.root), "mode": "resume", "profile": "assist",
                                          "mem": "8000M", "cpus": "1", "time": "01:00:00"}))
        gum = self.bin / "gum"
        gum.write_text(MOCK_GUM)
        gum.chmod(0o755)
        log = self.root / "gum.jsonl"
        env = dict(self.env, WIZARD_UI="gum", TEST_GUM_LOG=str(log))
        rc, output = self.execute(self.args, env=env)
        self.assertEqual(rc, 0, output)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        values = [call[call.index("--value") + 1] for call in calls if call[0] == "input"]
        self.assertEqual(values, ["12000M", "2", "02:00:00"])

    def test_cancel_at_menu_or_input_creates_no_run_or_defaults(self):
        for answers in (":cancel\n", "6\n1\nn\n:cancel\n", "6\n1\nn\n\x04\n", "6\n1\nn\n\x1b\n", "6\n1\nn\n\x03\n"):
            with self.subTest(answers=repr(answers)):
                rc, output = self.execute(self.args, answers)
                self.assertEqual(rc, 130, output)
                self.assertFalse((self.parent / "latest").exists())
                self.assertFalse((Path(self.env["HOME"]) / ".agentrun/wizard-last").exists())

    def test_gum_cancel_is_not_treated_as_empty_input(self):
        gum = self.bin / "gum"
        gum.write_text(MOCK_GUM)
        gum.chmod(0o755)
        env = dict(self.env, WIZARD_UI="gum", TEST_GUM_LOG=str(self.root / "gum.jsonl"), TEST_GUM_CANCEL_HEADER="CPU cores")
        rc, output = self.execute(self.args, env=env)
        self.assertEqual(rc, 130, output)
        self.assertFalse((self.parent / "latest").exists())

    def test_previous_defaults_and_bind_paths_are_restored(self):
        extra = self.root / "extra mount"
        extra.mkdir()
        answers = f"6\n1\nn\n\n\n\ny\n{extra}\n/extra:ro\nn\ny\n"
        rc, output = self.execute(self.args, answers)
        self.assertEqual(rc, 0, output)
        state_file = Path(self.env["HOME"]) / ".agentrun/wizard-last"
        state = json.loads(state_file.read_text())
        self.assertEqual(state["bind"], [f"{extra}:/extra:ro"])
        self.assertEqual(state_file.stat().st_mode & 0o777, 0o600)
        gum = self.bin / "gum"
        gum.write_text(MOCK_GUM)
        gum.chmod(0o755)
        log = self.root / "gum.jsonl"
        env = dict(self.env, WIZARD_UI="gum", TEST_GUM_LOG=str(log))
        rc, output = self.execute(["wizard"], env=env)
        self.assertEqual(rc, 0, output)
        calls = [json.loads(line) for line in log.read_text().splitlines()]
        mode_menu = next(call for call in calls if call[:3] == ["choose", "--header", "Select run mode"])
        self.assertEqual(mode_menu[3], "resume")
        fields = {call[call.index("--header") + 1].split(" (")[0]: call[call.index("--value") + 1]
                  for call in calls if call[0] == "input"}
        self.assertEqual(fields["Memory"], "12000M")
        self.assertEqual(fields["CPU cores"], "2")
        self.assertEqual(fields["Walltime"], "02:00:00")
        self.assertIn("/extra:ro", (self.parent / "latest/apptainer_exec.sh").read_text())

    def test_displayed_command_preserves_shell_specials_and_settings(self):
        capture = self.root / "captured.json"
        self.env["TEST_CAPTURE"] = str(capture)
        script = r'''source "$1"; shift
command_prepare() {
    local mode="$1"; shift
    parse_run_args "$@"
    python3 - "$mode" "$AGENT" "$(cd "$REPO" && pwd)" "${MEM:-$(profile_mem "$mode")}" "${CPUS:-$(profile_cpus "$mode")}" "${TIME_LIMIT:-$(profile_time "$mode")}" "$PROMPT" <<'PY'
import json, os, sys
from pathlib import Path
Path(os.environ["TEST_CAPTURE"]).write_text(json.dumps(sys.argv[1:]))
PY
}
command_wizard "$@"
'''
        prompt = "--literal 'quotes' $(touch injected) `touch injected`"
        answers = f"2\n1\nn\n\n\n\n\n\n\nn\nn\nn\n\n{prompt}\ny\n"
        rc, output = self.execute([], answers, command=["bash", "-c", script, "bash", str(LAUNCHER), "--agent", "codex"])
        self.assertEqual(rc, 0, output)
        expected = json.loads(capture.read_text())
        self.assertEqual(expected[-1], prompt)
        line = next(line.strip() for line in output.replace("\r", "").splitlines() if line.startswith("  agentrun experiment"))
        self.assertEqual(shlex.split(line)[-1], prompt)
        replay = script[:script.index('command_wizard "$@"')] + 'agentrun() { command_prepare "$@"; };\n' + line
        result = subprocess.run(["bash", "-c", replay, "bash", str(LAUNCHER)], cwd=self.root, env=self.env,
                                capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(capture.read_text()), expected)
        self.assertFalse((self.root / "injected").exists())


if __name__ == "__main__":
    unittest.main()
