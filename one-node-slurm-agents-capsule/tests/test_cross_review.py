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
from agent_cli import Reviewer

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
if args and args[0]=='sandbox':
    if (home/'sandbox-policy-broken').exists():
        print('Sandbox allowed writes to review inputs',file=sys.stderr)
        sys.exit(1)
    if (home/'sandbox-unavailable').exists():
        print("bwrap: Can't bind mount /oldroot/ on /newroot/: Invalid argument",file=sys.stderr)
        sys.exit(1)
    print('CAPSULE_REVIEW_SANDBOX_READ_ONLY_OK');sys.exit(0)
assert os.environ['AGENTRUN_ROLE']=='reviewer'
assert 'CLAUDECODE' not in os.environ
assert 'AGENT_REVIEW_SOCKET' not in os.environ
assert not any('bypass' in a for a in args)
provider='codex' if 'exec' in args else 'claude'
if provider=='codex':
    assert 'sandbox_mode="read-only"' in args
    assert any(a.startswith('mcp_servers.capsule-input.command=') for a in args)
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
if mode=='environment-question':
    result.update(kind='question',verdict='none',coverage='incomplete',limitations=['Input access failed'],questions=[{'question_id':'environment','text':'Please repair the input reader','evidence':[]}])
if mode=='sandbox-unavailable':
    assert context['input_access']['shell_sandbox_available'] is False
    assert context['input_access']['read_only'] is True
if mode=='finding':
    result.update(verdict='request_changes', findings=[{'finding_id':'f1','severity':'major',
        'confidence':'high','basis':'observed','evidence_method':'static_source',
        'file':'source/code.py','line':1,'message':'A defect','suggestion':'Fix it',
        'evidence':['source/code.py']}])
if context['round']>=2:
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

    def test_rechecks_continue_past_twenty_rounds_with_latest_files(self):
        ident = self.start("finding")
        previous = self.wait(ident)
        self.assertEqual(previous["verdict"], "request_changes", previous)
        thread = self.reviews.threads[previous["review_thread_id"]]
        # Old persisted caps and an expired cached Slurm end time must not block rechecks.
        thread.update(max_rounds=2, consumed_rounds=100, deadline=time.time() - 3600)
        self.reviews.config.update(max_exchanges=1, reply_timeout=1, thread_timeout=1,
                                   job_deadline=time.time() - 3600)
        for number in range(2, 23):
            (self.repo / "code.py").write_text(f"value = {number}\n")
            self.assertEqual(self.reviews.call("status", {"review_id": previous["review_id"]})["applicability"], "stale")
            for job, _ in self.reviews.jobs.values():
                job.join(timeout=2)
            findings = self.reviews.rounds[previous["review_id"]].get("result", {}).get("findings", [])
            response = {"responses": [
                {"finding_id": finding["finding_id"], "action": "fixed", "reason": "Checked latest changes",
                 "evidence": ["source/code.py"]} for finding in findings]}
            current = self.reviews.call("recheck", {"review_id": previous["review_id"],
                "request_id": f"recheck-{number}", "response": response})
            self.reviews.tick()
            state = self.wait(current["review_id"])
            self.assertEqual(state["status"], "success", state)
            self.assertEqual(state["verdict"], "approve", state)
            self.assertEqual(state["round"], number)
            self.assertIsNone(state["remaining_rounds"])
            self.assertEqual(state["applicability"], "valid")
            self.assertNotEqual(state["session_id"], previous["session_id"])
            snapshot = self.run / "reviews" / state["review_id"] / "input/source/code.py"
            self.assertEqual(snapshot.read_text(), f"value = {number}\n")
            previous = state

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

    def test_broken_bwrap_uses_confined_input_mcp_without_weakening_sandbox(self):
        home = self.home / ".reviewer/codex"
        home.mkdir(parents=True)
        (home / "sandbox-unavailable").touch()
        ident = self.start("sandbox-unavailable")
        state = self.wait(ident)
        self.assertEqual(state["status"], "success", state)
        self.assertFalse(state["input_access"]["shell_sandbox_available"])
        self.assertEqual(state["input_access"]["transport"], "capsule-input MCP")
        diagnostic = self.run / "reviews/runtime/codex/probe-sandbox/read/stderr.log"
        self.assertIn("bwrap:", diagnostic.read_text())

    def test_environment_question_needs_no_fabricated_file_reference(self):
        ident = self.start("environment-question")
        state = self.wait(ident)
        self.assertEqual(state["status"], "waiting_reply", state)
        self.assertEqual(state["question"]["payload"]["questions"][0]["evidence"], [])

    def test_permissive_sandbox_probe_is_not_treated_as_a_mount_failure(self):
        home = self.home / ".reviewer/codex"
        home.mkdir(parents=True)
        (home / "sandbox-policy-broken").touch()
        ident = self.start("approve")
        state = self.wait(ident)
        self.assertEqual(state["status"], "failed", state)
        self.assertEqual(state["error_kind"], "sandbox_probe_failed")
        self.assertIsNone(state["remaining_rounds"])
        self.assertFalse((home / "calls.jsonl").exists())

    def test_invalid_brief_is_rejected_before_launch_or_budget_consumption(self):
        for brief in (
            "Please review\nthis text",
            "x" * 5000,
            str(self.run / "artifacts/missing.md"),
        ):
            with (
                self.subTest(brief=brief[:20]),
                self.assertRaisesRegex(ValueError, "brief"),
            ):
                self.reviews.call(
                    "run", {"request_id": str(len(brief)), "brief": brief}
                )
        self.assertEqual(self.reviews.rounds, {})
        self.assertEqual(self.reviews.peers, {})

    def test_omitted_large_file_cannot_be_approved(self):
        with (self.repo / "large.png").open("wb") as stream:
            stream.truncate(review_snapshot.MAX_FILE + 1)
        self.git("add", ".")
        ident = self.start("approve", one_shot=True)
        state = self.wait(ident)
        self.assertEqual(state["status"], "failed", state)
        self.assertIn("Approval contradicts", state["error"])

    def test_reply_wait_has_no_deadline_and_cancel_keeps_partial_conversation(self):
        ident = self.start()
        self.wait(ident)
        with self.reviews.lock:
            self.reviews.rounds[ident]["reply_deadline"] = time.time() - 1
            self.reviews.threads[self.reviews.rounds[ident]["review_thread_id"]]["deadline"] = time.time() - 1
        with patch.object(review.time, "time", return_value=time.time() + 86400):
            self.reviews.tick()
        self.assertEqual(self.wait(ident)["status"], "waiting_reply")
        self.reviews.call("cancel", {"review_id": ident, "request_id": "cancel"})
        self.assertEqual(self.wait(ident)["status"], "cancelled")
        self.assertIn("question", (self.run / "reviews" / ident / "conversation.md").read_text())

    def test_peer_auth_only_copies_changed_bytes_and_preserves_refresh(self):
        home = self.root / 'peer-home'
        peer = Reviewer('codex', home, self.root / 'peer-state', self.root / 'peer-runtime',
                        self.home, RUNTIME / 'install-agent.sh', self.root / 'peer-cache', binary=str(self.binary))
        self.addCleanup(peer.close)
        worker = self.home / '.codex/auth.json'
        worker.write_text('{"other-run":"newer"}')
        peer.sync_credentials()
        self.assertEqual(worker.read_text(), '{"other-run":"newer"}')
        refreshed = b'{\n  "refresh": "new-value"\n}\n'
        (home / '.codex/auth.json').write_bytes(refreshed)
        peer.sync_credentials()
        self.assertEqual(worker.read_bytes(), refreshed)
        self.assertEqual(worker.stat().st_mode & 0o777, 0o600)
        worker.write_text('{"other-run":"newest"}')
        peer.close()
        self.assertEqual(worker.read_text(), '{"other-run":"newest"}')


    def test_auth_failure_does_not_consume_round_and_never_uses_worker_provider(self):
        (self.home / ".codex/auth.json").unlink()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "CODEX_API_KEY": ""}):
            ident = self.start()
            state = self.wait(ident)
        self.assertEqual(state["status"], "failed")
        self.assertIsNone(state["remaining_rounds"])
        self.assertEqual(state["provider"], "codex")
        self.assertFalse(
            (self.root / "persisted/codex/.codex/sessions/rollout.jsonl").exists()
        )

    def test_execution_timeout_stops_reviewer_and_keeps_diagnostics(self):
        self.reviews.config["active_timeout"] = 0.15
        ident = self.start("timeout")
        state = self.wait(ident)
        self.assertEqual(state["status"], "timeout", state)
        self.assertIsNone(state["remaining_rounds"])
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

    def test_cli_timeout_is_unlimited_by_default_and_invalid_values_are_rejected(self):
        self.assertEqual(self.reviews.config["active_timeout"], 0)
        for timeout in (-1, True, "600", float("inf"), float("nan")):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(ValueError, "CLI timeout"):
                review.Reviews(dict(self.config, active_timeout=timeout))

    def test_legacy_extend_is_unnecessary_and_cannot_add_a_cap(self):
        ident = self.start("finding")
        self.wait(ident)
        for number, maximum in enumerate((1, 3, 1000000)):
            state = self.reviews.call("extend", {"request_id": f"legacy-{number}",
                "review_id": ident, "max_rounds": maximum, "reason": "legacy client"})
            self.assertIsNone(state["remaining_rounds"])
            self.assertNotIn("max_rounds", self.reviews.threads[state["review_thread_id"]])

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

    def test_many_exchanges_and_legacy_restart_have_no_expired_limits(self):
        self.reviews.config["active_timeout"] = 60
        ident = self.start("questions-forever")
        for number in range(7):
            state = self.wait(ident)
            self.assertEqual(state["status"], "waiting_reply", state)
            self.reviews.rounds[ident]["active_seconds"] = 1000000
            self.reviews.call("reply", {"review_id": ident, "request_id": f"answer-{number}",
                "reply_to": state["question"]["message_id"], "message": {
                    "answers": [{"question_id": "q1", "answer": "Evidence", "evidence": []}],
                    "questions": [], "include": []}})
        state = self.wait(ident)
        self.assertEqual(state["status"], "waiting_reply", state)
        self.assertIsNone(state["remaining_exchanges"])
        thread = self.reviews.threads[state["review_thread_id"]]
        thread.update(max_rounds=2, consumed_rounds=100, deadline=time.time() - 86400)
        self.reviews.rounds[ident]["reply_deadline"] = time.time() - 86400
        self.reviews.close()
        self.config.update(thread_timeout=1, reply_timeout=1, max_exchanges=1,
                           job_deadline=time.time() - 86400)
        self.reviews = review.Reviews(self.config)
        self.addCleanup(self.reviews.close)
        self.assertNotIn("deadline", self.reviews.threads[state["review_thread_id"]])
        self.brief.write_text("approve")
        next_round = self.reviews.call("recheck", {"review_id": ident,
            "request_id": "after-restart", "response": {"responses": []}})
        self.reviews.tick()
        restarted = self.wait(next_round["review_id"])
        self.assertEqual(restarted["status"], "success", restarted)
        self.assertEqual(restarted["verdict"], "approve", restarted)
        self.assertIsNone(restarted["remaining_rounds"])
        self.assertIsNone(restarted["remaining_exchanges"])

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
