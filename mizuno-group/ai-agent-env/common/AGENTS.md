# Shared AI Agent Rules

These rules apply to Antigravity, Claude Code, Codex, and any future agent launched through `agentrun`.

## Execution Boundary

- Run agents inside a Slurm job and Apptainer capsule.
- Use the login node only to inspect files, prepare commands, and submit jobs.
- Do not run GPU workloads or non-trivial Python workloads directly on the login node.
- Keep agent changes inside the mounted workspace and run directory.

## Python And Slurm

- Python environments are managed with uv.
- Do not use `pip install` directly.
- Before generating an `srun` or `sbatch` command that invokes Python, identify the project venv and source it inside the Slurm command or job script.
- Follow the local `CLAUDE.md` Slurm partition, time, memory, and GPU guidance.

## Git Safety

- Do not overwrite user changes.
- Do not run destructive git operations unless explicitly requested.
- Do not push, force-push, rebase, or reset without explicit approval.
- Write patches and reports to the run ledger when working inside a capsule.

## Secrets

- Do not read SSH keys, API tokens, `.env` files, OAuth tokens, or agent auth files.
- Do not store authentication state in this repository.
- Bind only the minimum required auth metadata into the capsule.

## Observability

- Write live state under `/runs/live`.
- Write final outputs under `/runs/artifacts`.
- Required live outputs are `status.json`, `heartbeat.txt`, `stdout.log`, `stderr.log`, and `command_log.jsonl`.
- Required final outputs are `report.md`, `git_diff.patch`, and `metrics.json`.

## Testing

- Validate configuration before launching a run.
- Use `doctor` to check host tools, images, and auth state.
- Use `dry-run` before running Slurm and Apptainer commands.
- Use `smoke-test` before real assist or experiment mode.
- Use `verify-run` after each run.

# BASE GUIDELINES
Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

# CODING STANDARDS
- Unless otherwise instructed by the user, all code comments, docstrings, and documentation must be written in English.
- Implement code in a strict, fail-fast manner: validate assumptions explicitly, raise clear errors on unexpected inputs or states, and minimize silent or implicit fallback behavior.
