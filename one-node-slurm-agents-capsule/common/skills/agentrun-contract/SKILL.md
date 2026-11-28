---
name: agentrun-contract
description:
  Required output files, formats, and update timing for agentrun batch runs. Use
  this when a batch run's start prompt lists "Required outputs", or when the user
  of an interactive session asks for a report or the run outputs.
---

# agentrun output contract

This contract is for batch runs (the start prompt has a user goal and a
"Required outputs" list). In an interactive session, write these files only when
the user asks.

You are running inside an agentrun capsule. The host uses `agentrun verify-run`
to check your outputs after the job finishes. Failing to write required files, or
writing them in the wrong format, causes verify-run to fail even if your exit code
is 0.

## Container paths

```text
/workspace          the target repository (read/write)
/runs               run ledger (read/write) — write all outputs here
/scratch            per-run scratch space (read/write)
/node-scratch       optional compute-node SSD space (read/write)
/cache              per-run cache (read/write; not shared across runs)
/home/sandbox/ai-agent-config/common/hooks    shared hooks (read-only)
/home/sandbox/ai-agent-config/common/skills   shared skills (read-only)
```

All output paths below are relative to `/runs`.

The host mounts `.agent-runs/<run_id>/scratch` and
`.agent-runs/<run_id>/cache` at `/scratch` and `/cache`. Their contents belong to
that run and remain in its directory until removed; later runs get separate
directories, even on the same node.

If the compute node has `/scratch/<submission-user>`, it is mounted at
`/node-scratch` and `AGENTRUN_NODE_SCRATCH` is set to `/node-scratch`; otherwise
the variable is empty and this mount is omitted. This is separate from `/scratch`.
SSD contents stay on that node, are shared by that user's runs on the same node,
and are neither archived nor removed by agentrun. Keep final outputs under `/runs`.

## Files required by every batch run

agentrun creates every file below before the agent starts, and agentrun and its
hooks keep the `live/` ones; only the files marked **you** are yours to write.

| path | written by | notes |
| ---- | ---------- | ----- |
| `live/status.json` | agentrun | `running` while hooks see commands; `success`/`failed` from the exit code |
| `live/heartbeat.txt` | hooks | refreshed on every command |
| `live/stdout.log`, `live/stderr.log` | agentrun | |
| `live/command_log.jsonl`, `live/events.jsonl` | hooks | |
| `live/current_task.md` | **you** (optional) | one line of what you are doing now |
| `artifacts/report.md` | **you** | **must be non-empty** |
| `artifacts/git_diff.patch` | **you** | `git diff` output; empty if no changes |
| `artifacts/metrics.json` | **you** | summary metrics; `{}` is acceptable |
| `artifacts/run_title.txt` | **you** | **must be non-empty**; one lowercase line, about five words |

## Additional files per mode

| mode | extra required files |
| ---- | -------------------- |
| `experiment` | `artifacts/proposed_next.yaml` |
| `campaign` | `artifacts/proposed_next.yaml`, `artifacts/proposed_train.sbatch` |

The launcher also creates `capsule.yaml`, `prompt.txt`, and `goal.yaml`, and the
job runner writes `live/exit_code.txt` and `live/slurm_job_id.txt`.
`verify-run` checks these runtime records as well as the agent outputs above.
Prepare-only or unfinished runs may not pass verification yet.

## `live/current_task.md`

Optional: one line on what you are doing right now, for someone watching the run.

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

## `artifacts/run_title.txt`

At completion, write a short summary of the work: one lowercase line, about five
words, for example `trained cifar baseline model`. The runner uses it when naming
the finished run directory. `verify-run` rejects a missing or empty title.

## Common mistakes

- Writing outputs to `/workspace` instead of `/runs` — verify-run only checks `/runs`
- Leaving `artifacts/report.md` empty — verify-run explicitly checks non-empty
- Leaving `artifacts/run_title.txt` empty — verify-run explicitly checks non-empty
- Writing invalid JSON — verify-run runs `jq` on metrics.json
- Writing `live/status.json` or `live/heartbeat.txt` yourself — agentrun and its hooks own them
