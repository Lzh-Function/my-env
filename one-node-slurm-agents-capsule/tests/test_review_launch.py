"""Exercise the actual capsule supervisor without Slurm or a model request."""

import json
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import test_cross_review as fixtures
from review_launch import update_codex_mcp_environment


class ReviewLaunchTests(unittest.TestCase):
    def test_codex_mcp_environment_is_replaced_without_losing_preferences(self):
        for original in (
            '[mcp_servers.cross-review.env]\nAGENT_REVIEW_SOCKET = "old"\nEXTRA = "keep"\n',
            '[mcp_servers."cross-review".env]\nAGENT_REVIEW_SOCKET = "old"\nEXTRA = "keep"\n',
            'env = { AGENT_REVIEW_SOCKET = "old", EXTRA = "keep" }\n',
            'env.AGENT_REVIEW_SOCKET = "old"\nenv.EXTRA = "keep"\n',
        ):
            with (
                self.subTest(original=original),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory) / "config.toml"
                path.write_text(
                    'model = "saved-model"\nmodel_reasoning_effort = "low"\n'
                    'developer_instructions = """\n[mcp_servers.cross-review.env]\nkeep this instruction\n"""\n'
                    '[mcp_servers.cross-review]\ncommand = "agent-review"\n'
                    + original
                    + '\n[[entries]]\nname = "keep-array-item"\n[mcp_servers.other]\ncommand = "keep-other"\n'
                )
                for socket in ("/tmp/first/review.sock", "/tmp/second/review.sock"):
                    update_codex_mcp_environment(
                        path,
                        {"AGENT_REVIEW_SOCKET": socket, "UV_CACHE_DIR": "/cache/uv"},
                    )
                    config = tomllib.loads(path.read_text())
                    self.assertEqual(config["model"], "saved-model")
                    self.assertEqual(config["model_reasoning_effort"], "low")
                    self.assertEqual(
                        config["developer_instructions"],
                        "[mcp_servers.cross-review.env]\nkeep this instruction\n",
                    )
                    self.assertEqual(config["entries"], [{"name": "keep-array-item"}])
                    self.assertEqual(
                        config["mcp_servers"]["other"]["command"], "keep-other"
                    )
                    self.assertEqual(
                        config["mcp_servers"]["cross-review"]["env"],
                        {
                            "AGENT_REVIEW_SOCKET": socket,
                            "UV_CACHE_DIR": "/cache/uv",
                            "EXTRA": "keep",
                        },
                    )

    def scenario(self, crash=False):
        fixture = fixtures.CrossReviewTests(
            "test_idempotency_and_stale_question_rejection"
        )
        fixture.setUp()
        if crash:
            fixture.brief.write_text("timeout")
        self.addCleanup(fixture.doCleanups)
        (fixture.run / "session.json").write_text(
            '{"mode":"assist","run_id":"launcher-test","session_key":"session-test"}'
        )
        (fixture.home / ".claude").mkdir(exist_ok=True)
        binary = fixture.root / "bin"
        binary.mkdir()
        installer = fixture.root / "fake-installer.sh"
        installer.write_text(
            '#!/bin/sh\nset -eu\nmkdir -p "$HOME/.local/bin"\ncp '
            + shlex.quote(str(fixture.binary))
            + ' "$HOME/.local/bin/codex"\nchmod +x "$HOME/.local/bin/codex"\n'
        )
        curl = binary / "curl"
        curl.write_text(
            f'#!{sys.executable}\nimport shutil,sys\nshutil.copyfile({str(installer)!r},sys.argv[sys.argv.index("-o")+1])\n'
        )
        curl.chmod(0o755)
        worker = fixture.root / "worker.py"
        worker.write_text(f"""
import json, os, signal, subprocess, sys, time
from pathlib import Path
client={str(fixtures.RUNTIME / "agent-review")!r}
def call(*args):
    value=subprocess.run([sys.executable,client,*args],capture_output=True,text=True,check=True)
    return json.loads(value.stdout)
state=call('run','--request-id','start','--brief',{str(fixture.brief)!r})
if {crash!r}:
    for _ in range(300):
        records=list((Path({str(fixture.run)!r})/'reviews'/state['review_id']/'turns').glob('*/status.json'))
        active=[json.loads(p.read_text()) for p in records if json.loads(p.read_text()).get('pid')]
        if active:
            commandline=Path(f'/proc/{{active[0]["pid"]}}/cmdline').read_bytes()
            if b'_launch' not in commandline and b'--json' in commandline:break
        time.sleep(.02)
    assert active
    state['reviewer_pid']=active[0]['pid']
    supervisor=os.getppid()
    children=Path(f'/proc/{{supervisor}}/task/{{supervisor}}/children').read_text().split()
    candidates=[int(p) for p in children if int(p)!=os.getpid()]
    assert len(candidates)==1, candidates
    os.kill(candidates[0],signal.SIGKILL)
else:
    for _ in range(15):
        state=call('events',state['review_id'],'--after',str(state['cursor']),'--wait-seconds','1')
        if state['status']=='waiting_reply':break
    assert state['status']=='waiting_reply',state
Path({str(fixture.root / "worker-state.json")!r}).write_text(json.dumps(dict(state,socket=os.environ['AGENT_REVIEW_SOCKET'])))
sys.exit(42)
""")
        env = dict(
            os.environ,
            HOME=str(fixture.home),
            PATH=str(binary) + ":" + os.environ["PATH"],
        )
        result = subprocess.run(
            [
                sys.executable,
                str(fixtures.RUNTIME / "review_launch.py"),
                "--agent",
                "claude",
                "--run-dir",
                str(fixture.run),
                "--workspace",
                str(fixture.repo),
                "--reviewer-store",
                str(fixture.root / "persisted"),
                "--cache-dir",
                str(fixture.root / "cache"),
                "--",
                sys.executable,
                str(worker),
            ],
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 42, result.stdout + result.stderr)
        worker_state = json.loads((fixture.root / "worker-state.json").read_text())
        state = json.loads(
            (
                fixture.run / "reviews" / worker_state["review_id"] / "state.json"
            ).read_text()
        )
        self.assertEqual(state["status"], "failed" if crash else "cancelled")
        request = json.loads(
            (
                fixture.run / "reviews" / worker_state["review_id"] / "request.json"
            ).read_text()
        )
        self.assertEqual(request["parent_run"], "launcher-test")
        self.assertEqual(request["parent_session_key"], "session-test")
        self.assertFalse(Path(worker_state["socket"]).exists())
        if not crash:
            self.assertTrue(list((fixture.root / "persisted/codex").glob("**/*.jsonl")))
        else:
            process = Path("/proc") / str(worker_state["reviewer_pid"]) / "stat"
            self.assertTrue(
                not process.exists()
                or process.read_text().rsplit(")", 1)[1].split()[0] == "Z"
            )
        self.assertFalse(
            (fixture.run / "artifacts/agent-cli.json").exists(),
            "Reviewer overwrote worker metadata",
        )
        self.assertTrue(
            (
                fixture.run
                / "reviews/runtime/codex/installation/artifacts/agent-cli.json"
            ).is_file()
        )
        config = json.loads(
            (fixture.run / "container_config/review-mcp.json").read_text()
        )
        self.assertEqual(
            config["mcpServers"]["cross-review"]["env"]["AGENT_REVIEW_SOCKET"],
            worker_state["socket"],
        )

    def test_installer_dialogue_and_parent_exit_preserve_native_history(self):
        self.scenario()

    def test_service_sigkill_recovers_recorded_reviewer_process(self):
        self.scenario(crash=True)


if __name__ == "__main__":
    unittest.main()
