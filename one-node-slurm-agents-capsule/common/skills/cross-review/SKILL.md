---
name: cross-review
description: Request an independent Codex or Claude Code audit of research or code through the capsule review runtime, answer reviewer questions, and address findings. Use when cross-agent review is requested or part of an agreed research workflow.
---

# Cross Review

Use the capsule's `cross-review` MCP tools, or `agent-review` CLI when MCP is unavailable. Both use the same state. The runtime chooses the opposite provider; do not launch provider CLIs or nested `agentrun` jobs yourself.

Write a brief under `/runs/artifacts/` stating the purpose, claims, acceptance criteria, scope, existing checks, evidence paths and known limitations. For research, consult [research.md](references/research.md). Explicitly include untracked code and relevant artifacts; the runtime otherwise captures tracked source and the diff against the worker-start commit. Do not include private files, caches or whole datasets.

Start with `review_start`, retaining the review ID and event cursor. Use a fresh `request_id` for every new operation, and reuse that ID only to retry the identical operation. Poll `review_events` (maximum wait: 20 seconds) until a question or terminal state arrives. Do not finish the task while a requested review is still running.

When `waiting_reply` arrives, call `review_reply` with its message ID and answers to all question IDs. Use this shape:

```json
{"answers":[{"question_id":"q1","answer":"Explanation or unavailable","evidence":[]}],"questions":[],"include":[]}
```

`evidence` references paths in the snapshot manifest; `include` explicitly names additional original files to capture. Explanations are claims; provide inspectable evidence. Keep the reviewed files unchanged during this dialogue. If the snapshot must change, cancel this round before modifying it and use the remaining round to review the changed snapshot.

After a result, inspect its applicability and every finding. Fix valid problems and document evidence-based disagreement or deferral. Do not automatically apply a reviewer's patch. Call `review_recheck` after fixing or rebutting findings, providing a response for every previous finding:

```json
{"responses":[{"finding_id":"f1","action":"disputed","reason":"Explanation","evidence":["source/evaluation.py"]}]}
```

Actions are `fixed`, `disputed`, or `deferred`. Recheck captures current files and starts a fresh reviewer conversation with the previous findings, dialogue and your response. The runtime preserves finding IDs and requires a disposition for each prior finding. Your own `fixed` response does not resolve a finding.

The default budget is two review rounds (initial plus recheck), with at most three question/answer exchanges within each round. Stop after approval or budget exhaustion; report remaining disagreements, unavailable evidence or execution failures. Additional rounds require an explicit continuation request; do not create another review thread to bypass the budget.

Report the reviewer provider, review ID, target ID, verdict, applicability, unresolved findings and limitations. A successful process is not approval; stale, incomplete or failed reviews cannot establish completion. Supplied test logs do not count as independently reproduced tests.

For CLI use, run `agent-review --help` and its subcommand help. `run`, `reply`, `recheck`, `status`, `events`, and `cancel` correspond to the MCP operations. `run --one-shot --wait` explicitly opts out of dialogue; never silently switch to it after a continuation failure.
