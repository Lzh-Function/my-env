#!/usr/bin/env python3
"""Native Codex + real MCP, with a local Responses fixture; no model or real auth.

Run in an isolated container with no external network and mcp==1.26.0 installed:
  python native-codex-review-probe.py /path/to/codex /path/to/runtime/agentrun
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


def main():
    binary, runtime = (Path(p).resolve() for p in sys.argv[1:])
    sys.path.insert(0, str(runtime))
    from agent_cli import Reviewer
    from review import MESSAGE_SCHEMA
    from review_snapshot import capture

    with tempfile.TemporaryDirectory(prefix="native-review-probe-") as temporary:
        root = Path(temporary)
        repo, run, home = root / "repo", root / "run", root / "worker-home"
        repo.mkdir()
        (run / "artifacts").mkdir(parents=True)
        (home / ".codex").mkdir(parents=True)
        (home / ".codex/auth.json").write_text('{"OPENAI_API_KEY":"local-probe-key"}')
        for args in (
            ("init", "-q"),
            ("config", "user.name", "Fixture"),
            ("config", "user.email", "fixture@example.invalid"),
        ):
            subprocess.run(
                ["git", "-C", str(repo), *args], check=True, capture_output=True
            )
        nonce = "EVIDENCE_" + root.name
        (repo / "code.py").write_text(f"value = '{nonce}'\n")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
        brief = run / "artifacts/brief.md"
        brief.write_text("Review the source using capsule-input MCP.\n")
        directory = run / "input"
        manifest = capture(repo, run, directory, "HEAD", [], str(brief), {})
        fake_bin = root / "bin"
        fake_bin.mkdir()
        requests, failures = [], []
        result = {
            "kind": "review_result",
            "target_id": manifest["target_id"],
            "summary": "Read evidence through snapshot-only MCP",
            "verdict": "approve",
            "coverage": "complete",
            "limitations": [],
            "checked_scope": ["source/code.py"],
            "praise": [],
            "questions": [],
            "findings": [],
            "prior_dispositions": [],
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                try:
                    body = self.rfile.read(int(self.headers["Content-Length"]))
                    request = json.loads(body)
                    requests.append(request)
                    number = len(requests)
                    if number > 4:
                        raise AssertionError("Unexpected extra model request")
                    tools = []
                    for tool in request["tools"]:
                        for function in tool.get("tools", [tool]):
                            if "read_file" in function.get("name", ""):
                                tools.append(
                                    (
                                        tool.get("name")
                                        if tool.get("type") == "namespace"
                                        else None,
                                        function["name"],
                                    )
                                )
                    if number <= 2:
                        assert len(tools) == 1, [
                            t.get("name", t.get("type")) for t in request["tools"]
                        ]
                        if number == 2:
                            assert manifest["target_id"] in json.dumps(request["input"])
                        item = {
                            "id": f"fc_{number}",
                            "type": "function_call",
                            "status": "completed",
                            "call_id": f"call_{number}",
                            "name": tools[0][1],
                            "arguments": json.dumps(
                                {
                                    "path": "manifest.json"
                                    if number == 1
                                    else "source/code.py"
                                }
                            ),
                        }
                        if tools[0][0]:
                            item["namespace"] = tools[0][0]
                    else:
                        assert nonce in json.dumps(request["input"]), request["input"]
                        item = {
                            "id": "msg_final",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(result),
                                    "annotations": [],
                                }
                            ],
                        }
                    response = {
                        "id": f"resp_{number}",
                        "object": "response",
                        "created_at": 1,
                        "status": "completed",
                        "model": "gpt-5.4",
                        "output": [item],
                        "usage": {
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "total_tokens": 2,
                        },
                    }
                    initial = {**item, "status": "in_progress"}
                    initial[
                        "arguments" if item["type"] == "function_call" else "content"
                    ] = "" if item["type"] == "function_call" else []
                    events = [
                        {
                            "type": "response.created",
                            "response": {
                                **response,
                                "status": "in_progress",
                                "output": [],
                            },
                        },
                        {
                            "type": "response.output_item.added",
                            "output_index": 0,
                            "item": initial,
                        },
                    ]
                    if item["type"] == "function_call":
                        events += [
                            {
                                "type": "response.function_call_arguments.delta",
                                "item_id": item["id"],
                                "output_index": 0,
                                "delta": item["arguments"],
                            },
                            {
                                "type": "response.function_call_arguments.done",
                                "item_id": item["id"],
                                "output_index": 0,
                                "arguments": item["arguments"],
                            },
                        ]
                    else:
                        events += [
                            {
                                "type": "response.content_part.added",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "part": {
                                    "type": "output_text",
                                    "text": "",
                                    "annotations": [],
                                },
                            },
                            {
                                "type": "response.output_text.delta",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "delta": item["content"][0]["text"],
                            },
                            {
                                "type": "response.output_text.done",
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "text": item["content"][0]["text"],
                            },
                        ]
                    events += [
                        {
                            "type": "response.output_item.done",
                            "output_index": 0,
                            "item": item,
                        },
                        {"type": "response.completed", "response": response},
                    ]
                    payload = "".join(
                        "event: " + e["type"] + "\ndata: " + json.dumps(e) + "\n\n"
                        for e in events
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception as error:  # noqa: BLE001 -- return fixture assertion failures to the native client
                    failures.append(str(error))
                    print(
                        "Local Responses fixture error: " + str(error),
                        file=sys.stderr,
                        flush=True,
                    )
                    self.send_error(400, str(error)[:200])

        http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        # Explicit provider configuration avoids any default OpenAI/ChatGPT
        # discovery or websocket endpoint. The container has no external network.
        cli = fake_bin / "codex-probe"
        overrides = [
            "-c",
            'model_provider="local_probe"',
            "-c",
            'model_providers.local_probe.name="Local fixture"',
            "-c",
            "model_providers.local_probe.base_url="
            + json.dumps(f"http://127.0.0.1:{http.server_port}/v1"),
            "-c",
            'model_providers.local_probe.wire_api="responses"',
            "-c",
            'model_providers.local_probe.env_key="OPENAI_API_KEY"',
            "-c",
            "model_providers.local_probe.requires_openai_auth=false",
            "-c",
            "model_providers.local_probe.supports_websockets=false",
            "--disable",
            "api_key_model_discovery",
            "--disable",
            "enable_request_compression",
            "-c",
            "shell_environment_policy.set.PATH="
            + json.dumps(str(fake_bin) + ":/usr/local/bin:/usr/bin:/bin"),
        ]
        cli.write_text(
            f"#!{sys.executable}\nimport os,sys\nargs=sys.argv[1:]\ncount=3 if args[:2]==['exec','resume'] else 1 if args and args[0] in ('exec','sandbox') else 0\nos.execv({str(binary)!r}, [{str(binary)!r}, *args[:count], *{overrides!r}, *args[count:]])\n"
        )
        cli.chmod(0o755)
        env = {
            "PATH": str(fake_bin) + ":/usr/local/bin:/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "HOME": str(home),
            "OPENAI_API_KEY": "local-probe-key",
            "OPENAI_BASE_URL": f"http://127.0.0.1:{http.server_port}/v1",
        }
        peer = None
        try:
            with patch.dict(os.environ, env, clear=True):
                peer = Reviewer(
                    "codex",
                    root / "review-home",
                    root / "persisted",
                    root / "runtime",
                    home,
                    runtime / "install-agent.sh",
                    root / "cache",
                    binary=str(cli),
                    model="gpt-5.4",
                )
                cancelled = threading.Event()
                peer.ensure(cancelled)
                peer.prepare_input_transport(directory, cancelled)
                prompt = "Read manifest.json and source/code.py with capsule-input MCP. Return only the supplied schema."
                answer, session, _elapsed = peer.turn(
                    directory,
                    prompt,
                    MESSAGE_SCHEMA,
                    root / "turn",
                    None,
                    90,
                    cancelled,
                )
                assert not failures, failures
                assert answer == result, answer
                assert len(requests) == 3, len(requests)
                assert session
                assert (repo / "code.py").read_text() == f"value = '{nonce}'\n"
                print(
                    "NATIVE_CODEX_MCP_REVIEW_OK: native CLI read manifest and evidence; "
                    f"shell_sandbox_available={peer.input_access['shell_sandbox_available']}; "
                    "no external model/auth used"
                )
        except Exception:
            for log in root.rglob("stderr.log"):
                print(
                    str(log) + "\n" + log.read_text(errors="replace")[-8000:],
                    file=sys.stderr,
                )
            for request in requests:
                print("fixture request keys=" + repr(list(request)), file=sys.stderr)
            raise
        finally:
            if peer:
                peer.close()
            http.shutdown()
            http.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    main()
