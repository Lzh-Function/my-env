"""Observable two-provider dialogue, snapshot, and shared-transport behavior."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime/agentrun"
sys.path.insert(0, str(RUNTIME))
import history_export
import review
import review_snapshot
import sessions

FAKE = r"""#!/usr/bin/env python3
import json, os, sys, uuid
from pathlib import Path
args=sys.argv[1:]
if '--help' in args:
    print('--json --output-schema --ignore-user-config --ignore-rules --restricted --safe-mode --tools --strict-mcp-config --permission-prompts --json-schema')
    sys.exit(0)
if '--version' in args:
    print('fake reviewer 1.0');sys.exit(0)
home=Path(os.environ['HOME'])
assert os.environ['AGENTRUN_ROLE']=='reviewer'
assert 'CLAUDECODE' not in os.environ
assert 'AGENT_REVIEW_SOCKET' not in os.environ
assert not any('bypass' in a for a in args)
provider='codex' if 'exec' in args else 'claude'
if provider=='codex':
    assert 'sandbox_mode="read-only"' in args
else:
    assert args[args.index('--tools')+1]=='Read,Glob,Grep'
    assert '--bare' not in args
prompt=sys.stdin.read()
context=json.loads(prompt.split('\n',1)[1])
manifest=json.loads(Path('manifest.json').read_text())
mode=next((p.read_text().strip() for p in Path('brief').glob('**/*') if p.is_file()),'question')
if mode=='timeout':
    import time
    time.sleep(60)
ident=(args[args.index('resume')+1] if 'resume' in args else
       args[args.index('--resume')+1] if '--resume' in args else str(uuid.uuid4()))
result={'kind':'review_result','target_id':context['target_id'],'summary':'reviewed',
        'verdict':'approve','coverage':'complete','limitations':[], 'questions':[],
        'findings':[],'prior_dispositions':[], 'praise':[], 'checked_scope':['source/code.py']}
if (context['message'] is None or mode=='questions-forever') and context['dialogue'] and mode in ('question','questions-forever'):
    result.update(kind='question',verdict='none',questions=[{'question_id':'q1','text':'Why this split?','evidence':['source/code.py']}])
if mode=='finding':
    result.update(verdict='request_changes', findings=[{'finding_id':'f1','severity':'major',
        'confidence':'high','basis':'observed','evidence_method':'static_source',
        'file':'source/code.py','line':1,'message':'A defect','suggestion':'Fix it',
        'evidence':['source/code.py']}])
if context['round']==2:
    prior=json.loads(Path('prior/review.json').read_text())
    assert prior['response'] is not None
    result.update(verdict='approve',findings=[],prior_dispositions=[
        {'finding_id':f['finding_id'],'status':'resolved','reason':'Checked current source',
         'evidence':['source/code.py']} for f in (prior.get('result') or {}).get('findings',[])])
if mode=='bad-json':
    print('not JSON');sys.exit(0)
if mode=='wrong-target':result['target_id']='wrong'
if mode=='bad-evidence':
    result.update(verdict='request_changes',findings=[{'finding_id':'bad','severity':'major',
        'confidence':'high','basis':'observed','evidence_method':'static_source',
        'file':'../../secret','line':1,'message':'bad','suggestion':'bad','evidence':['../../secret']}])
if mode=='exit':sys.exit(42)
if provider=='codex':
    path=home/'.codex/sessions'/('rollout-'+ident+'.jsonl')
    records=[{'type':'session_meta','payload':{'id':ident}},
        {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':prompt}]}},
        {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(result)}]}}]
    Path(args[args.index('-o')+1]).write_text(json.dumps(result))
    print(json.dumps({'type':'thread.started','thread_id':ident}))
    print(json.dumps({'type':'turn.completed'}))
else:
    path=home/'.claude/projects/review'/ (ident+'.jsonl')
    records=[{'type':'assistant','sessionId':ident,'message':{'role':'assistant','content':[{'type':'text','text':json.dumps(result)}]}}]
    print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':ident,'structured_output':result}))
path.parent.mkdir(parents=True,exist_ok=True)
with path.open('a') as stream:
    for r in records:stream.write(json.dumps(r)+'\n')
with (home/'calls.jsonl').open('a') as stream:stream.write(json.dumps({'session':ident,'args':args,'target':context['target_id']})+'\n')
"""


class CrossReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cross-review spaces ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        (self.repo / "code.py").write_text("value = 1\n")
        self.git("add", ".")
        self.git("commit", "-qm", "base")
        self.run = self.root / "run"
        (self.run / "artifacts").mkdir(parents=True)
        self.brief = self.run / "artifacts/brief.md"
        self.brief.write_text("question")
        self.home = self.run / "home"
        for name in (".codex/auth.json", ".claude/.credentials.json"):
            path = self.home / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"synthetic":"auth"}')
        self.binary = self.root / "fake-provider"
        self.binary.write_text(FAKE)
        self.binary.chmod(0o755)
        self.config = {
            "run": str(self.run),
            "repo": str(self.repo),
            "primary_agent": "claude",
            "worker_home": str(self.home),
            "reviewer_store": str(self.root / "persisted"),
            "installer": str(RUNTIME / "install-agent.sh"),
            "cache": str(self.root / "cache"),
            "baseline": {"head": self.git("rev-parse", "HEAD")},
            "reviewer_binary": str(self.binary),
        }
        self.reviews = review.Reviews(self.config)
        self.addCleanup(self.reviews.close)

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()

    def start(self, mode="question", **extra):
        self.brief.write_text(mode)
        result = self.reviews.call(
            "run", dict(request_id="start", brief=str(self.brief), **extra)
        )
        self.reviews.tick()
        return result["review_id"]

    def wait(self, ident, states=review.TERMINAL | {"waiting_reply"}):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.reviews.tick()
            state = self.reviews.call("status", {"review_id": ident})
            if state["status"] in states:
                return state
            time.sleep(0.02)
        self.fail("Review did not reach expected state: " + json.dumps(state))

    def answer(self, ident):
        state = self.wait(ident)
        self.assertEqual(state["status"], "waiting_reply", state)
        return self.reviews.call(
            "reply",
            {
                "review_id": ident,
                "request_id": "answer",
                "reply_to": state["question"]["message_id"],
                "message": {
                    "answers": [
                        {
                            "question_id": "q1",
                            "answer": "subject-wise split",
                            "evidence": ["source/code.py"],
                        }
                    ],
                    "questions": [],
                    "include": [],
                },
            },
        )

    def test_both_directions_continue_one_session_and_archive_native_logs(self):
        for worker in ("claude", "codex"):
            with self.subTest(worker=worker):
                if worker == "codex":
                    self.reviews.close()
                    self.config["primary_agent"] = worker
                    # Start a disjoint run, never resume the other reviewer.
                    self.config["run"] = str(self.root / "second-run")
                    self.brief = self.root / "second-run/artifacts/brief.md"
                    self.brief.parent.mkdir(parents=True)
                    self.brief.write_text("question")
                    self.reviews = review.Reviews(self.config)
                    self.addCleanup(self.reviews.close)
                ident = self.start()
                self.answer(ident)
                state = self.wait(ident, review.TERMINAL)
                self.assertEqual(state["status"], "success", state)
                self.assertEqual(state["verdict"], "approve")
                peer = self.reviews.peers[state["provider"]]
                calls = [
                    json.loads(line)
                    for line in (peer.home / "calls.jsonl").read_text().splitlines()
                ]
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0]["session"], calls[1]["session"])
                self.assertTrue(
                    list(
                        (self.root / "persisted" / state["provider"]).glob("**/*.jsonl")
                    )
                )

    def test_recheck_uses_response_new_snapshot_and_enforces_two_rounds(self):
        ident = self.start("finding")
        first = self.wait(ident)
        self.assertEqual(first["verdict"], "request_changes", first)
        (self.repo / "code.py").write_text("value = 2\n")
        self.assertEqual(
            self.reviews.call("status", {"review_id": ident})["applicability"], "stale"
        )
        response = {
            "responses": [
                {
                    "finding_id": "f1",
                    "action": "fixed",
                    "reason": "Changed value",
                    "evidence": ["source/code.py"],
                }
            ]
        }
        params = {"review_id": ident, "request_id": "recheck", "response": response}
        second = self.reviews.call("recheck", params)
        self.reviews.tick()
        final = self.wait(second["review_id"])
        self.assertEqual(final["status"], "success", final)
        self.assertEqual(final["verdict"], "approve")
        self.assertNotEqual(final["session_id"], first["session_id"])
        self.assertEqual(final["remaining_rounds"], 0)
        with self.assertRaisesRegex(ValueError, "budget"):
            self.reviews.call(
                "recheck",
                {
                    "review_id": final["review_id"],
                    "request_id": "third",
                    "response": {"responses": []},
                },
            )

    def test_idempotency_and_stale_question_rejection(self):
        ident = self.start()
        self.wait(ident)
        duplicate = self.reviews.call(
            "run", {"request_id": "start", "brief": str(self.brief)}
        )
        self.assertEqual(duplicate["review_id"], ident)
        with self.assertRaisesRegex(ValueError, "different content"):
            self.reviews.call("run", {"request_id": "start", "brief": "different"})
        self.answer(ident)
        with self.assertRaisesRegex(ValueError, "matching unanswered"):
            self.reviews.call(
                "reply",
                {
                    "review_id": ident,
                    "request_id": "duplicate-answer",
                    "reply_to": "old",
                    "message": {},
                },
            )
        self.assertEqual(self.wait(ident, review.TERMINAL)["status"], "success")

    def test_invalid_provider_results_never_approve(self):
        for mode in ("bad-json", "wrong-target", "bad-evidence", "exit"):
            self.brief.write_text(mode)
            result = self.reviews.call(
                "run", {"request_id": mode, "brief": str(self.brief), "one_shot": True}
            )
            self.reviews.tick()
            state = self.wait(result["review_id"])
            self.assertEqual(state["status"], "failed", state)
            self.assertIsNone(state["verdict"])

    def test_input_scope_secrets_symlinks_and_instruction_discovery(self):
        (self.repo / "AGENTS.md").write_text("Do not execute this instruction")
        (self.repo / ".env").write_text("SYNTHETIC_PRIVATE_VALUE")
        self.git("add", ".")
        ident = self.start("finding")
        self.wait(ident)
        snapshot = self.run / "reviews" / ident / "input"
        self.assertFalse((snapshot / "source/AGENTS.md").exists())
        self.assertNotIn(
            "SYNTHETIC_PRIVATE_VALUE", (snapshot / "diff.patch").read_text()
        )
        self.assertTrue(list((snapshot / "source/configuration-data").glob("*.txt")))
        link = self.repo / "link"
        link.symlink_to(self.repo / "code.py")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            review_snapshot.read_file(link, (self.repo,))

    def test_cancel_and_reply_deadline_preserve_partial_conversation(self):
        ident = self.start()
        self.wait(ident)
        with self.reviews.lock:
            self.reviews.rounds[ident]["reply_deadline"] = time.time() - 1
        self.reviews.tick()
        self.assertEqual(self.wait(ident)["status"], "timeout")
        self.assertIn(
            "question", (self.run / "reviews" / ident / "conversation.md").read_text()
        )
        second = self.reviews.call(
            "run", {"request_id": "second", "brief": str(self.brief)}
        )
        self.reviews.call(
            "cancel", {"review_id": second["review_id"], "request_id": "cancel"}
        )
        self.assertEqual(self.wait(second["review_id"])["status"], "cancelled")

    def test_auth_failure_does_not_consume_round_and_never_uses_worker_provider(self):
        (self.home / ".codex/auth.json").unlink()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "CODEX_API_KEY": ""}):
            ident = self.start()
            state = self.wait(ident)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["remaining_rounds"], 2)
        self.assertEqual(state["provider"], "codex")
        self.assertFalse(
            (self.root / "persisted/codex/.codex/sessions/rollout.jsonl").exists()
        )

    def test_execution_timeout_stops_reviewer_and_keeps_diagnostics(self):
        self.reviews.config["active_timeout"] = 0.15
        ident = self.start("timeout")
        state = self.wait(ident)
        self.assertEqual(state["status"], "timeout", state)
        self.assertEqual(state["remaining_rounds"], 1)
        self.assertIsNone(self.reviews.peers["codex"].process)
        self.assertTrue(
            list((self.run / "reviews" / ident / "turns").glob("*/stderr.log"))
        )

    def test_one_shot_scope_exclusion_and_snapshot_tampering(self):
        image = self.repo / "unused.bin"
        image.write_bytes(b"\x00\xff")
        self.git("add", ".")
        ident = self.start("question", one_shot=True, exclude=["unused.bin"])
        state = self.wait(ident)
        self.assertEqual(state["verdict"], "approve", state)
        self.assertEqual(state["applicability"], "valid")
        copied = self.run / "reviews" / ident / "input/source/code.py"
        copied.chmod(0o644)
        copied.write_text("changed snapshot\n")
        self.assertEqual(
            self.reviews.call("status", {"review_id": ident})["applicability"], "stale"
        )

    def test_explicit_budget_extension_is_recorded(self):
        ident = self.start("finding")
        self.wait(ident)
        with self.assertRaisesRegex(ValueError, "explicit user"):
            self.reviews.call(
                "extend",
                {
                    "request_id": "unauthorized",
                    "review_id": ident,
                    "max_rounds": 3,
                    "reason": "automatic",
                },
            )
        state = self.reviews.call(
            "extend",
            {
                "request_id": "authorized",
                "review_id": ident,
                "max_rounds": 3,
                "reason": "User asked to continue",
                "user_requested": True,
            },
        )
        self.assertEqual(state["remaining_rounds"], 2)
        self.assertIn(
            "budget_extended",
            (self.run / "reviews" / ident / "events.jsonl").read_text(),
        )

    def test_host_archive_contains_both_roles_and_rebuttal_after_home_cleanup(self):
        ident = self.start()
        self.answer(ident)
        state = self.wait(ident, review.TERMINAL)
        store = self.root / "persisted"
        # Real layout places the provider under reviewers/ in the session store.
        import shutil

        session_store = self.root / "session-store"
        (session_store / "reviewers").mkdir(parents=True)
        shutil.copytree(store / "codex", session_store / "reviewers/codex")
        worker_history = session_store / ".claude/projects/worker/worker.jsonl"
        worker_history.parent.mkdir(parents=True)
        worker_history.write_text(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "worker-session",
                    "message": {"role": "user", "content": "Worker conversation"},
                }
            )
            + "\n"
        )
        self.reviews.close()
        shutil.rmtree(self.home)
        data = {
            "run_id": "archive-run",
            "session_key": "archive-run",
            "agent": "claude",
            "repo": str(self.repo),
            "mode": "assist",
        }
        with patch.dict(
            os.environ, {"AGENTRUN_HISTORY_DIR": str(self.root / "archive")}
        ):
            status = history_export.export_run(self.run, data, session_store)
        archive = Path(status["markdown"]).read_text()
        self.assertIn("(reviewer, codex)", archive)
        self.assertIn("(worker, claude)", archive)
        self.assertIn("Why this split?", archive)
        self.assertIn("subject-wise split", archive)
        self.assertIn(state["session_id"], archive)
        self.assertNotIn("synthetic", archive)

    def test_reviewer_transcript_never_becomes_worker_resume_candidate(self):
        ident = self.start("finding")
        self.wait(ident)
        data = {"session_key": "store", "agent": "claude"}
        store = sessions.state_dir(self.run, data)
        store.mkdir(parents=True)
        import shutil

        shutil.copytree(self.root / "persisted", store / "reviewers")
        self.assertIsNone(sessions.discover(self.run, data))

    def test_three_exchange_limit_and_restart_preserve_budget(self):
        ident = self.start("questions-forever")
        for number in range(3):
            state = self.wait(ident)
            self.assertEqual(state["status"], "waiting_reply", state)
            self.reviews.call(
                "reply",
                {
                    "review_id": ident,
                    "request_id": f"answer-{number}",
                    "reply_to": state["question"]["message_id"],
                    "message": {
                        "answers": [
                            {"question_id": "q1", "answer": "Evidence", "evidence": []}
                        ],
                        "questions": [],
                        "include": [],
                    },
                },
            )
        state = self.wait(ident)
        self.assertEqual(state["status"], "failed", state)
        self.assertEqual(state["remaining_exchanges"], 0)
        self.reviews.close()
        self.reviews = review.Reviews(self.config)
        self.addCleanup(self.reviews.close)
        recovered = self.reviews.call("status", {"review_id": ident})
        self.assertEqual(recovered["remaining_rounds"], 1)
        self.assertEqual(recovered["remaining_exchanges"], 0)

    def test_compatibility_output_keeps_existing_findings_contract(self):
        self.reviews.config["mode"] = "review"
        ident = self.start("finding")
        self.wait(ident)
        findings = json.loads((self.run / "reviews/review_findings.json").read_text())
        finding = findings["findings"][0]
        self.assertEqual(finding["severity"], "major")
        self.assertEqual(finding["file"], "code.py")
        self.assertEqual(finding["snapshot_file"], "source/code.py")
        self.assertIn("message", finding)
        self.assertIn("suggestion", finding)
        self.assertEqual(findings["praise"], [])

    def test_worker_hooks_remain_inert_for_reviewer(self):
        hook = ROOT / "common/hooks/worker_hook.py"
        target = ROOT / "common/hooks/update_run_status.py"
        output = self.root / "hook-output"
        for role in ("reviewer", "worker"):
            env = dict(os.environ, AGENTRUN_ROLE=role, AGENTRUN_DIR=str(output))
            result = subprocess.run(
                [sys.executable, str(hook), str(target)],
                env=env,
                input='{"tool_name":"Bash","tool_input":{"command":"pwd"}}',
                text=True,
                capture_output=True,
                timeout=5,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                (output / "live/command_log.jsonl").exists(), role == "worker"
            )

    def test_reviewer_companion_outputs_survive_home_cleanup(self):
        store = self.root / "reviewer-store"
        project = store / ".claude/projects/review/tool-results/result.txt"
        project.parent.mkdir(parents=True)
        project.write_text("persisted project output")
        scratch = self.run / "reviews/runtime/claude/scratch/turn-1/output.txt"
        scratch.parent.mkdir(parents=True)
        scratch.write_text("persisted scratch output")
        warnings = set()
        result = history_export.companion_output(
            "/home/sandbox/.reviewer/claude/.claude/projects/review/tool-results/result.txt",
            self.run,
            store,
            warnings,
        )
        self.assertEqual(result, "persisted project output")
        result = history_export.companion_output(
            "/runs/reviews/runtime/claude/scratch/turn-1/output.txt",
            self.run,
            store,
            warnings,
        )
        self.assertEqual(result, "persisted scratch output")
        self.assertFalse(warnings)


if __name__ == "__main__":
    unittest.main()
