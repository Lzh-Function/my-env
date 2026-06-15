---
name: agentrun-contract
description:
  Required output files, formats, and update timing for agentrun runs. Use this
  whenever you are running inside an agentrun capsule and need to know what files
  to write, where, and in what format.
---

# agentrun output contract

You are running inside an agentrun capsule. The host uses `agentrun verify-run`
to check your outputs after the job finishes. Failing to write required files, or
writing them in the wrong format, causes verify-run to fail even if your exit code
is 0.

## Container paths

```text
/workspace          the target repository (read/write)
/runs               run ledger (read/write) — write all outputs here
/scratch            ephemeral scratch space (read/write)
/cache              persistent cache (read/write across runs on the same node)
/home/sandbox/ai-agent-config   this config repository (read-only)
```

All output paths below are relative to `/runs`.

## Files required by every run

These must exist when the job exits regardless of mode.

| path | format | notes |
| ---- | ------ | ----- |
| `live/status.json` | JSON | see format below |
| `live/heartbeat.txt` | ISO-8601 timestamp | update periodically while working |
| `live/stdout.log` | plain text | append agent output; may be empty |
| `live/stderr.log` | plain text | may be empty |
| `live/command_log.jsonl` | JSONL | one JSON object per line |
| `live/events.jsonl` | JSONL | one JSON object per line; may be empty |
| `live/current_task.md` | markdown | one-liner of what you are doing right now |
| `artifacts/report.md` | markdown | **must be non-empty** |
| `artifacts/git_diff.patch` | patch | `git diff` output; empty if no changes |
| `artifacts/metrics.json` | JSON | summary metrics; `{}` is acceptable |

## Additional files per mode

| mode | extra required files |
| ---- | -------------------- |
| `experiment` | `artifacts/proposed_next.yaml` |
| `campaign` | `artifacts/proposed_next.yaml`, `artifacts/proposed_train.sbatch` |
| `review` | `reviews/review_findings.json` |
| `multi-review` | `reviews/claude.md`, `reviews/codex.md`, `reviews/antigravity.md`, `reviews/summary.md`, `reviews/disagreements.json`, `reviews/final_recommendation.md` |

## `live/status.json` format

Write this file last, after all other outputs are complete.

```json
{"status": "success", "agent": "<agent>", "mode": "<mode>", "job_id": "<SLURM_JOB_ID>"}
```

The `status` field must be one of: `success`, `failed`, `cancelled`, `timeout`.
Use `success` only when all required outputs are written without error.
On failure, write `failed` and include `"exit_code"` if available.

## `live/heartbeat.txt`

Update this file periodically (every few minutes) to signal the job is alive.

```bash
date -Iseconds > /runs/live/heartbeat.txt
```

## `live/current_task.md`

Keep this updated to describe what you are doing right now. One line is enough.

```
Refactoring dataset loader to support streaming mode.
```

## `artifacts/report.md`

Must be non-empty. Write a human-readable summary of what you did, what changed,
and any notable findings. Minimum viable content:

```markdown
# Agent Run Report

## Summary
What was accomplished.

## Changes
List of files changed or actions taken.

## Notes
Anything the operator should know.
```

## `artifacts/metrics.json`

A JSON object with numeric or string metrics relevant to the run. `{}` is valid
if there is nothing meaningful to report.

```json
{"duration_s": 120, "files_changed": 3, "tests_passed": 42}
```

## `artifacts/git_diff.patch`

Generate with:

```bash
git -C /workspace diff HEAD > /runs/artifacts/git_diff.patch
```

If no changes were made, write an empty file:

```bash
: > /runs/artifacts/git_diff.patch
```

## Common mistakes

- Writing outputs to `/workspace` instead of `/runs` — verify-run only checks `/runs`
- Leaving `live/status.json` as `{}` — must have a `status` field
- Leaving `artifacts/report.md` empty — verify-run explicitly checks non-empty
- Writing invalid JSON/JSONL — verify-run runs `jq` on status.json, metrics.json, and command_log.jsonl
