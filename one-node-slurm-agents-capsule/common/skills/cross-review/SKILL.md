---
name: cross-review
description: Request an independent Codex or Claude Code audit of research or code through the capsule review runtime, answer reviewer questions, and address findings. Use when cross-agent review is requested or part of an agreed research workflow.
---

# Cross Review

Use the capsule's `cross-review` MCP tools, or `agent-review` CLI when MCP is unavailable. Both use the same state. The runtime chooses the opposite provider; do not launch provider CLIs or nested `agentrun` jobs yourself.

Write a brief under `/runs/artifacts/` stating the purpose, claims, acceptance criteria, scope, existing checks, evidence paths and known limitations. For research, consult [research.md](references/research.md). Explicitly include untracked code and relevant artifacts; the runtime otherwise captures tracked source and the diff against the worker-start commit. Do not include private files, caches or whole datasets.

Pass the brief's **file path**, such as `/runs/artifacts/review-brief.md`, to `review_start.brief` or `--brief`; do not pass its text. The runtime prioritizes explicit evidence and changed source, and records automatically omitted oversized/context files in `manifest.json`. Inspect omissions; narrow the scope with `exclude` and provide smaller text artifacts when necessary. An omitted required input prevents complete approval.

Start with `review_start`, retaining the review ID and event cursor. Use a fresh `request_id` for every new operation, and reuse that ID only to retry the identical operation. Poll `review_events` (maximum wait: 20 seconds) until a question or terminal state arrives. Do not finish the task while a requested review is still running.

When `waiting_reply` arrives, call `review_reply` with its message ID and answers to all question IDs. Use this shape:

```json
{"answers":[{"question_id":"q1","answer":"Explanation or unavailable","evidence":[]}],"questions":[],"include":[]}
```

`evidence` references paths in the snapshot manifest; `include` explicitly names additional original files to capture. Explanations are claims; provide inspectable evidence. Keep the reviewed files unchanged during this dialogue. If the snapshot must change, cancel this round before modifying it and start a new round to review the changed snapshot.

For environment/access problems, use `evidence: []` and explain the limitation in text rather than inventing a file reference. Codex reviewers receive the snapshot-only `capsule-input` MCP reader; a failed inner shell sandbox does not prevent those file reads and never permits unrestricted commands. Report `input_reader_unavailable` separately from a review verdict.

After a result, inspect its applicability and every finding. Fix valid problems and document evidence-based disagreement or deferral. Do not automatically apply a reviewer's patch. Call `review_recheck` after fixing or rebutting findings, providing a response for every previous finding:

```json
{"responses":[{"finding_id":"f1","action":"disputed","reason":"Explanation","evidence":["source/evaluation.py"]}]}
```

Actions are `fixed`, `disputed`, or `deferred`. Recheck captures current files and starts a fresh reviewer conversation with the previous findings, dialogue and your response. The runtime preserves finding IDs and requires a disposition for each prior finding. Your own `fixed` response does not resolve a finding.

Recheck returns a new `review_id` and cursor in the same `review_thread_id`. Replace the current ID and cursor with those returned values before polling, replying, or reporting the next round. The previous ID continues to return the previous round's final result.

Review rounds and question/answer exchanges are unlimited. Continue the dialogue, fixes and rechecks until the agents agree on the current version or the user stops the review. Recheck every later edit before reporting final approval; an approval for an older snapshot does not cover newer changes. The runtime has no thread deadline or reply-wait deadline, and does not cache the Slurm job end time because the allocation can be extended. Parent-session exit and explicit cancellation still stop the service. Report unavailable evidence or execution failures, and do not present them as approval.

Report the reviewer provider, review ID, target ID, verdict, applicability, unresolved findings and limitations. A successful process is not approval; stale, incomplete or failed reviews cannot establish completion. Supplied test logs do not count as independently reproduced tests.

For CLI use, run `agent-review --help` and its subcommand help. `run`, `reply`, `recheck`, `status`, `events`, and `cancel` correspond to the MCP operations. `run --one-shot --wait` explicitly opts out of dialogue; never silently switch to it after a continuation failure.
