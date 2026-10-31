"""Observable two-provider dialogue, snapshot, and shared-transport behavior."""

import json
import os
import re
import signal
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
    # The real agy prints its usage to stderr.
    print('--json --output-schema --ignore-user-config --ignore-rules --restricted --safe-mode --tools --strict-mcp-config --permission-prompts --json-schema --conversation --settings --disable-slash-commands --print-timeout --input-format --output-format',
          file=sys.stderr if os.environ.get('AGENTRUN_AGENT')=='antigravity' else sys.stdout)
    sys.exit(0)
if '--version' in args:
    print('fake reviewer 1.0');sys.exit(0)
home=Path(os.environ['HOME'])
if args[:1]==['models']:
    print('Fetching available models...',file=sys.stderr)
    print('fake-flash-low\tFake Flash (Low)\nfake-flash-high\tFake Flash (High)');sys.exit(0)
if args[:2]==['debug','models']:
    if (home/'models-broken').exists():
        print('not a catalog');sys.exit(0)
    print(json.dumps({'models':[{'slug':'gpt-test','display_name':'GPT Test','description':'Workhorse','visibility':'list',
        'default_reasoning_level':'medium','supported_reasoning_levels':[{'effort':'low'},{'effort':'high'}]},
        {'slug':'hidden-model','visibility':'hide','supported_reasoning_levels':[]}]}));sys.exit(0)
if os.environ.get('AGENTRUN_AGENT')=='claude' and '--input-format' in args:
    request=json.loads(sys.stdin.readline())
    assert request['request']['subtype']=='initialize' and args[args.index('--setting-sources')+1]==''
    print(json.dumps({'type':'system','subtype':'hook_started'}))
    print(json.dumps({'type':'control_response','response':{'subtype':'success','request_id':request['request_id'],
        'response':{'account':{'email':'private@example.invalid'},'models':[
            {'value':'opus','resolvedModel':'claude-opus-test','displayName':'Opus','description':'Complex work','supportedEffortLevels':['low','high']},
            {'value':'claude-haiku-old','resolvedModel':'claude-haiku-old','displayName':'Haiku old'}]}}}));sys.exit(0)
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
provider=os.environ['AGENTRUN_AGENT']
assert provider==('codex' if 'exec' in args else provider)
if provider=='codex':
    assert 'sandbox_mode="read-only"' in args
    assert any(a.startswith('mcp_servers.capsule-input.command=') for a in args)
elif provider=='antigravity':
    settings=json.loads(Path(args[args.index('--settings')+1]).read_text())
    assert settings['permissions']['deny']==['command(*)','write_file(*)','read_url(*)','execute_url(*)','mcp(*)']
    assert settings['permissions']['allow']==['read_file('+os.getcwd()+')']
    assert 'review_hook.py' in (home/'.gemini/config/hooks.json').read_text()
else:
    assert args[args.index('--tools')+1]=='Read,Glob,Grep'
    assert '--bare' not in args
prompt=sys.stdin.read()
if provider=='antigravity':
    prompt=json.loads(prompt)['message']['content']
context=json.loads(prompt.split('\n',1)[1])
manifest=json.loads(Path('manifest.json').read_text())
mode=next((p.read_text().strip() for p in Path('brief').glob('**/*') if p.is_file()),'question')
if mode=='timeout':
    import time
    time.sleep(60)
ident=(args[args.index('resume')+1] if 'resume' in args else
       args[args.index('--resume')+1] if '--resume' in args else
       args[args.index('--conversation')+1] if '--conversation' in args else str(uuid.uuid4()))
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
if mode=='line-evidence':
    result.update(verdict='request_changes', findings=[{'finding_id':'f1','severity':'major',
        'confidence':'high','basis':'observed','evidence_method':'static_source',
        'file':'source/code.py','line':1,'message':'A defect','suggestion':'Fix it',
        'evidence':['source/code.py:1','source/code.py:1-1','diff.patch']}])
if mode=='unknown-line-evidence':
    result.update(verdict='request_changes', findings=[{'finding_id':'f1','severity':'major',
        'confidence':'high','basis':'observed','evidence_method':'static_source',
        'file':'source/code.py','line':1,'message':'A defect','suggestion':'Fix it',
        'evidence':['source/missing.py:1']}])
if '--model' in args and args[args.index('--model')+1]=='cli-rejects-model':
    print("The 'cli-rejects-model' model is not supported when using Codex with a ChatGPT account.",file=sys.stderr)
    sys.exit(1)
if provider=='codex':
    path=home/'.codex/sessions'/('rollout-'+ident+'.jsonl')
    records=[{'type':'session_meta','payload':{'id':ident}},
        {'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':prompt}]}},
        {'type':'response_item','payload':{'type':'message','role':'assistant','content':[{'type':'output_text','text':json.dumps(result)}]}}]
    Path(args[args.index('-o')+1]).write_text(json.dumps(result))
    print(json.dumps({'type':'thread.started','thread_id':ident}))
    print(json.dumps({'type':'turn.completed'}))
elif provider=='antigravity':
    if (home/'.gemini/antigravity-cli/antigravity-oauth-token').read_text()=='expired':
        print(json.dumps({'event':'result','result':{'status':'ERROR','conversation_id':ident,'error':'Please log in again'}}))
        sys.exit(1)
    path=home/'.gemini/antigravity-cli/brain'/(ident+'.jsonl')
    records=[{'conversation':ident,'result':result}]
    print(json.dumps({'event':'step_update','step_update':{}}))
    if mode=='agy-response':
        # agy 1.4 without structured_output: the checked JSON first, then a pretty copy.
        print(json.dumps({'event':'result','result':{'status':'SUCCESS','conversation_id':ident,'json_schema':{'type':'object'},
            'response':json.dumps(result)+'\n'+json.dumps(dict(result,summary='later text'),indent=2)}}))
    else:
        print(json.dumps({'event':'result','result':{'status':'SUCCESS','conversation_id':ident,
            'structured_output':result,'usage':{'tokens':1}}}))
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
        for name in (".codex/auth.json", ".claude/.credentials.json",
                     ".gemini/antigravity-cli/antigravity-oauth-token", ".gemini/antigravity-cli/installation_id"):
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
        # The first Codex round starts the input MCP through uv, which can take several seconds.
        deadline = time.monotonic() + 30
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

    def provider_calls(self, provider):
        path = self.reviews.peers[provider].home / "calls.jsonl"
        return [json.loads(line)["args"] for line in path.read_text().splitlines()] if path.exists() else []

    def reopen(self, primary, **config):
        self.reviews.close()
        self.config.update(config, primary_agent=primary,
                           run=str(self.root / ("run-" + primary + "-" + str(len(config)))))
        self.run = Path(self.config["run"])
        self.brief = self.run / "artifacts/brief.md"
        self.brief.parent.mkdir(parents=True, exist_ok=True)
        self.brief.write_text("approve")
        self.reviews = review.Reviews(self.config)
        self.addCleanup(self.reviews.close)

    def test_models_lists_current_cli_catalog_without_account_data(self):
        listing = self.reviews.call("models", {})["reviewers"]
        self.assertEqual([item["provider"] for item in listing], ["codex", "antigravity"])
        codex, antigravity = listing
        self.assertTrue(codex["available"], codex)
        self.assertEqual([m["id"] for m in codex["models"]], ["gpt-test"])  # hidden models are dropped
        self.assertEqual(codex["models"][0]["efforts"], ["low", "high"])
        self.assertEqual(codex["configured"], {"model": None, "effort": None})
        self.assertEqual([m["id"] for m in antigravity["models"]], ["fake-flash-low", "fake-flash-high"])
        self.assertIn("omit effort", antigravity["notes"])
        with self.assertRaises(ValueError):
            self.reviews.call("models", {"reviewers": ["claude"]})  # the worker itself is never a reviewer
        self.reopen("codex")
        claude = self.reviews.call("models", {"reviewers": ["claude"]})["reviewers"][0]
        self.assertEqual([(m["id"], m["resolved"]) for m in claude["models"]],
                         [("opus", "claude-opus-test"), ("claude-haiku-old", "claude-haiku-old")])
        self.assertNotIn("private@example.invalid", json.dumps(claude))

    def test_antigravity_reviews_alongside_codex_with_its_own_thread(self):
        self.brief.write_text("question")
        group = self.reviews.call("run", dict(request_id="two", brief=str(self.brief), reviewers=["codex", "antigravity"],
                                              models={"antigravity": "fake-flash-high"}))
        self.reviews.tick()
        items = {item["provider"]: item for item in group["reviews"]}
        self.assertEqual(set(items), {"codex", "antigravity"})
        self.assertNotEqual(items["codex"]["review_thread_id"], items["antigravity"]["review_thread_id"])
        with self.assertRaisesRegex(ValueError, "Another review is active for antigravity"):
            self.reviews.call("run", dict(request_id="busy", brief=str(self.brief), reviewers=["antigravity"]))
        for provider in ("codex", "antigravity"):
            ident = items[provider]["review_id"]
            self.assertEqual(self.wait(ident)["status"], "waiting_reply")
            self.reviews.call("reply", {"review_id": ident, "request_id": "answer-" + provider,
                                        "reply_to": self.reviews.rounds[ident]["question"]["message_id"],
                                        "message": {"answers": [{"question_id": "q1", "answer": "subject-wise",
                                                                 "evidence": ["source/code.py"]}],
                                                    "questions": [], "include": []}})
            state = self.wait(ident, review.TERMINAL)
            self.assertEqual(state["verdict"], "approve", state)
        state = self.reviews.rounds[items["antigravity"]["review_id"]]
        self.assertEqual(state["model_used"], "fake-flash-high")
        calls = self.provider_calls("antigravity")
        self.assertEqual(len(calls), 2)
        self.assertIn("--conversation", calls[1])  # the answer continues the same conversation
        self.assertEqual(calls[1][calls[1].index("--conversation") + 1], state["session_id"])
        self.assertNotIn("--effort", calls[0])
        self.brief.write_text("approve")
        recheck = self.reviews.call("recheck", {"review_id": state["review_id"], "request_id": "recheck-agy",
                                                "response": {"responses": []}})
        self.assertEqual(recheck["provider"], "antigravity")
        self.reviews.tick()
        state = self.wait(recheck["review_id"], review.TERMINAL)
        self.assertEqual(state["verdict"], "approve", state)

    def test_antigravity_effort_and_missing_or_expired_login_are_reported(self):
        result = self.reviews.call("run", dict(request_id="agy-effort", brief=str(self.brief), reviewers=["antigravity"],
                                               models={"antigravity": "fake-flash-low"}, efforts={"antigravity": "high"}))
        self.reviews.tick()
        state = self.wait(result["review_id"], review.TERMINAL)
        self.assertEqual(state["error_kind"], "invalid_model", state)
        self.assertIn("omit effort", state["error"])
        (self.reviews.peers["antigravity"].home / ".gemini/antigravity-cli/antigravity-oauth-token").write_text("expired")
        result = self.reviews.call("run", dict(request_id="agy-expired", brief=str(self.brief), reviewers=["antigravity"]))
        self.reviews.tick()
        state = self.wait(result["review_id"], review.TERMINAL)
        self.assertEqual(state["error_kind"], "authentication", state)
        self.reopen("codex")
        __import__("shutil").rmtree(self.home / ".reviewer/antigravity")
        for name in ("antigravity-oauth-token", "installation_id"):
            (self.home / ".gemini/antigravity-cli" / name).unlink()
        result = self.reviews.call("run", dict(request_id="agy-missing", brief=str(self.brief), reviewers=["antigravity"]))
        self.reviews.tick()
        state = self.wait(result["review_id"], review.TERMINAL)
        self.assertEqual(state["error_kind"], "missing_authentication", state)

    def test_legacy_single_reviewer_config_still_applies_to_the_default_reviewer(self):
        self.reopen("claude", model="gpt-test", effort="low")
        listing = {item["provider"]: item["configured"] for item in self.reviews.call("models", {})["reviewers"]}
        self.assertEqual(listing, {"codex": {"model": "gpt-test", "effort": "low"},
                                   "antigravity": {"model": None, "effort": None}})

    def test_line_suffixed_evidence_is_normalized_but_unknown_paths_are_rejected(self):
        ident = self.start("line-evidence", reviewers=["antigravity"], one_shot=True)
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["status"], "success", state)  # agy starts even though its usage is on stderr
        findings = json.loads(Path(state["findings_path"]).read_text())["findings"]
        self.assertEqual(findings[0]["evidence"], ["source/code.py", "diff.patch"])
        prompt = next((self.run / "reviews" / ident / "turns").glob("*/prompt.txt")).read_text()
        self.assertIn("without a line suffix", prompt)
        self.brief.write_text("unknown-line-evidence")
        result = self.reviews.call("run", dict(request_id="unknown", brief=str(self.brief), one_shot=True,
                                               reviewers=["antigravity"]))
        self.reviews.tick()
        state = self.wait(result["review_id"], review.TERMINAL)
        self.assertEqual(state["error"], "Invalid evidence reference", state)

    def test_antigravity_result_is_read_from_the_first_json_in_its_response(self):
        ident = self.start("agy-response", reviewers=["antigravity"], one_shot=True)
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["verdict"], "approve", state)
        summary = json.loads(Path(state["findings_path"]).read_text())["summary"]
        self.assertEqual(summary, "reviewed")  # not the later copy

    def test_review_hook_allows_only_reads_inside_the_input(self):
        directory = self.root / "input"
        (directory / "source").mkdir(parents=True)

        def decide(name, args):
            result = subprocess.run([sys.executable, str(RUNTIME / "review_hook.py"), str(directory)],
                                    input=json.dumps({"toolCall": {"name": name, "args": args}}),
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)["decision"]

        self.assertEqual(decide("view_file", {"AbsolutePath": str(directory / "source/code.py")}), "allow")
        self.assertEqual(decide("grep_search", {"SearchPath": "source", "Query": "x"}), "allow")
        for name, args in (("view_file", {"AbsolutePath": "/home/sandbox/.codex/auth.json"}),
                           ("list_dir", {"DirectoryPath": "../.."}),
                           ("run_command", {"CommandLine": "cat manifest.json"}),
                           ("write_to_file", {"TargetFile": str(directory / "x")}),
                           ("read_url_content", {"Url": "https://example.invalid"}),
                           ("view_file", {"paths": "not-a-list"})):
            with self.subTest(name=name, args=args):
                self.assertEqual(decide(name, args), "deny")
        malformed = subprocess.run([sys.executable, str(RUNTIME / "review_hook.py"), str(directory)],
                                   input="not json", capture_output=True, text=True, timeout=10)
        self.assertEqual(json.loads(malformed.stdout)["decision"], "deny")

    def test_agent_selected_model_is_checked_passed_and_reported(self):
        ident = self.start("approve", one_shot=True, models={"codex": "gpt-test"}, efforts={"codex": "high"})
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["verdict"], "approve", state)
        self.assertEqual(state["model_selection"], {"model": "gpt-test", "model_source": "agent",
                                                    "effort": "high", "effort_source": "agent"})
        self.assertEqual(state["model_used"], "gpt-test")
        args = self.provider_calls("codex")[-1]
        self.assertEqual(args[args.index("--model") + 1], "gpt-test")
        self.assertIn('model_reasoning_effort="high"', args)
        self.assertIn("モデル: gpt-test (agent) / effort: high (agent)", Path(state["report_path"]).read_text())
        again = self.reviews.call("recheck", {"review_id": ident, "request_id": "recheck", "response": {"responses": []}})
        self.reviews.tick()
        state = self.wait(again["review_id"], review.TERMINAL)
        self.assertEqual(state["model_selection"]["model"], "gpt-test")  # recheck keeps the previous choice
        self.assertIn("gpt-test", self.provider_calls("codex")[-1])

    def test_claude_alias_or_resolved_name_is_accepted(self):
        self.reopen("codex")
        ident = self.start("approve", one_shot=True, models={"claude": "claude-opus-test"}, efforts={"claude": "low"})
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["verdict"], "approve", state)
        args = self.provider_calls("claude")[-1]
        self.assertEqual(args[args.index("--model") + 1], "claude-opus-test")
        self.assertEqual(args[args.index("--effort") + 1], "low")

    def test_unlisted_model_fails_before_the_turn_and_retry_keeps_the_round(self):
        ident = self.start("question", models={"codex": "retired-model"})
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["error_kind"], "invalid_model", state)
        self.assertEqual(state["recovery"]["available_models"], ["gpt-test"])
        self.assertIn("agent-review models --reviewers codex", state["recovery"]["list_command"])
        self.assertEqual(self.provider_calls("codex"), [])
        with self.assertRaises(ValueError):
            self.reviews.call("retry", {"review_id": ident, "request_id": "bad-effort", "model": "gpt-test", "effort": "Bad!"})
        retried = self.reviews.call("retry", {"review_id": ident, "request_id": "retry-model", "model": "gpt-test"})
        self.assertEqual(retried["review_id"], ident)
        self.answer(ident)
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["verdict"], "approve", state)
        self.assertEqual(state["round"], 1)
        self.assertEqual(state["model_used"], "gpt-test")
        events = self.reviews.call("events", {"review_id": ident})["events"]
        self.assertIn("model_retry", [event["kind"] for event in events])
        with self.assertRaisesRegex(ValueError, "invalid_model"):
            self.reviews.call("retry", {"review_id": ident, "request_id": "retry-success"})

    def test_unsupported_effort_is_rejected_before_the_turn(self):
        ident = self.start("approve", models={"codex": "gpt-test"}, efforts={"codex": "xhigh"})
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["error_kind"], "invalid_model", state)
        self.assertIn("does not support effort xhigh", state["error"])
        self.assertEqual(self.provider_calls("codex"), [])

    def test_user_configured_model_takes_priority_over_agent_choice(self):
        self.reopen("claude", reviewer_settings={"codex": {"model": "gpt-test", "effort": "low"}})
        with self.assertRaisesRegex(ValueError, "AGENT_REVIEW_CODEX_MODEL"):
            self.reviews.call("run", dict(request_id="agent-override", brief=str(self.brief),
                                          models={"codex": "other-model"}))
        self.assertEqual(self.reviews.rounds, {})
        self.assertEqual(self.reviews.call("models", {})["reviewers"][0]["configured"],
                         {"model": "gpt-test", "effort": "low"})
        ident = self.start("approve", one_shot=True)
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["model_selection"], {"model": "gpt-test", "model_source": "environment",
                                                    "effort": "low", "effort_source": "environment"})
        args = self.provider_calls("codex")[-1]
        self.assertEqual(args[args.index("--model") + 1], "gpt-test")
        # Only an explicit user request in the conversation overrides the launch setting.
        result = self.reviews.call("run", dict(request_id="user-override", brief=str(self.brief), one_shot=True,
                                               models={"codex": "gpt-test"}, efforts={"codex": "high"},
                                               model_source="user"))
        self.reviews.tick()
        state = self.wait(result["review_id"], review.TERMINAL)
        self.assertEqual(state["model_selection"]["effort_source"], "user")
        self.assertIn('model_reasoning_effort="high"', self.provider_calls("codex")[-1])

    def test_invalid_model_requests_are_rejected_before_any_review(self):
        for index, extra in enumerate((
                {"models": {"claude": "x"}}, {"models": {"codex": "bad name"}}, {"models": {"codex": "--flag"}},
                {"efforts": {"codex": "HIGH"}}, {"models": ["gpt-test"]}, {"model": "gpt-test"},
                {"model_source": "admin"}, {"reviewers": ["claude"]}, {"reviewers": ["gemini"]})):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.reviews.call("run", dict(request_id="invalid-model-" + str(index), brief=str(self.brief), **extra))
        self.assertEqual(self.reviews.rounds, {})

    def test_cli_judges_the_model_when_its_catalog_is_unavailable(self):
        self.reviews.peer("codex", __import__("threading").Event())
        (self.reviews.peers["codex"].home / "models-broken").write_text("")
        listing = self.reviews.call("models", {})["reviewers"][0]
        self.assertFalse(listing["available"], listing)
        self.assertEqual(listing["error_kind"], "model_list_unavailable")
        ident = self.start("approve", one_shot=True, models={"codex": "cli-rejects-model"})
        state = self.wait(ident, review.TERMINAL)
        self.assertEqual(state["error_kind"], "invalid_model", state)
        self.assertIsNone(state["recovery"]["available_models"])

    def agentrun_reviews(self, *args, expected=0):
        result = subprocess.run([str(RUNTIME / "agentrun"), "reviews", str(self.run), *args],
                                capture_output=True, text=True, timeout=20, cwd=self.root)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result.stdout if expected == 0 else result.stderr

    def test_agentrun_reviews_lists_numbered_threads_and_renders_one(self):
        ident = self.start("question", models={"codex": "gpt-test"})
        self.answer(ident)
        self.wait(ident, review.TERMINAL)
        events = self.run / "reviews" / ident / "events.jsonl"
        with events.open("a") as stream:  # mix terminal controls into reviewer-derived text
            stream.write(json.dumps({"sequence": 99, "kind": "failed", "sender": "runtime", "recipient": "worker",
                                     "timestamp": time.time(), "payload": {"error": "boom\x1b]0;owned\x07\x1b[31mred"}}) + "\n")
            stream.write('{"partial": ')  # a partially written line is ignored
        listing = self.agentrun_reviews()
        self.assertRegex(listing, r"\n +1  codex +終了 +1  approve .*gpt-test \(agent\)")
        self.assertIn("進行中 0", listing)
        dialogue = self.agentrun_reviews("1")
        self.assertIn("=== codex#1 ラウンド 1 — gpt-test (agent) ===", dialogue)
        self.assertIn("Q q1: Why this split?", dialogue)
        self.assertIn("A q1: subject-wise split", dialogue)
        self.assertIn("判定: approve", dialogue)
        self.assertIn("エラー: boom]0;owned[31mred", dialogue)
        self.assertNotIn("\x1b", dialogue)
        self.assertEqual(self.agentrun_reviews("--reviewer", "codex"), dialogue)
        self.assertEqual(self.agentrun_reviews(ident[:15]), dialogue)  # an ID prefix also works
        # Following a finished thread prints it and returns immediately.
        self.assertIn("<<< codex#1 が終了しました: approve", self.agentrun_reviews("1", "--follow"))
        self.assertIn("該当する監査がありません", self.agentrun_reviews("9", expected=2))

    def test_agentrun_reviews_defaults_to_latest_run_and_number(self):
        ident = self.start("approve", one_shot=True)
        self.wait(ident, review.TERMINAL)
        runs = self.root / ".agent-runs"
        runs.mkdir()
        (runs / "latest").symlink_to(self.run)
        result = subprocess.run([str(RUNTIME / "agentrun"), "reviews", "1"],
                                capture_output=True, text=True, timeout=20, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("=== codex#1 ラウンド 1 — CLI既定 (cli_default) ===", result.stdout)

    def test_agentrun_reviews_follow_shows_only_live_threads(self):
        done = self.start("approve", one_shot=True)
        self.wait(done, review.TERMINAL)
        self.brief.write_text("question")
        live = self.reviews.call("run", dict(request_id="follow-live", brief=str(self.brief)))["review_id"]
        self.reviews.tick()
        self.assertEqual(self.wait(live)["status"], "waiting_reply")
        self.assertIn("進行中 1", self.agentrun_reviews())
        process = subprocess.Popen([str(RUNTIME / "agentrun"), "reviews", str(self.run), "--follow"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.root,
                                   start_new_session=True)
        try:
            time.sleep(2)
            self.answer(live)  # the continuation is appended while following
            self.wait(live, review.TERMINAL)
            time.sleep(2.5)
        finally:
            os.killpg(process.pid, signal.SIGINT)  # like Ctrl+C in a terminal
            stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 130, stderr)
        self.assertNotIn("codex#1", stdout)  # threads that ended before following are not shown
        self.assertIn(">>> codex#2 を追跡します", stdout)
        self.assertIn("codex#2 reviewer → worker: question", stdout)
        self.assertIn("codex#2 worker → reviewer: answer", stdout)
        self.assertIn("<<< codex#2 が終了しました: approve", stdout)
        self.assertIn("進行中の監査はありません。新しい監査の開始を待っています", stdout)
        stamps = re.findall(r"^\[(\d\d-\d\d \d\d:\d\d:\d\d)\] codex#", stdout, re.MULTILINE)
        self.assertEqual(stamps, sorted(stamps))

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
