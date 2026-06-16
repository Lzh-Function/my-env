# Implementation Audit Against `plan.md`

Date: 2026-06-10

This audit records the current implementation state against `plan.md` and the fixes made before test execution.

## Current Issues Found

- `install.sh` originally changed `$HOME` by default. It now prints planned symlink commands by default and only writes symlinks when `--apply` is passed.
- `runtime/apptainer/build-images.sh` originally ran `apptainer build` immediately. It now defaults to dry-run and refuses `--run` outside a Slurm allocation by checking `SLURM_JOB_ID`.
- `runtime/apptainer/base-system.def` was missing. It now exists and uses `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04`.
- `agentrun` did not expose several commands named in `plan.md`. It now includes `agents`, `tail`, `open-run`, `verify-run --run-id`, and direct mode commands for `assist`, `experiment`, `campaign`, `review`, and `multi-review`.
- `agentrun` used `/home/sandbox/ai-agent-env` inside the container, while `plan.md` uses `/home/sandbox/ai-agent-config`. The dry-run mount and prompt now use `/home/sandbox/ai-agent-config`.
- `base-agent.def` hid agent installer failures with `|| true`. It now fails fast if an installer fails.
- `setup_templates.py` used an absolute local path and would require running Python on the login node. It has been removed; templates and adapters are tracked as normal files.
- Existing Claude assets were staged as moved into `mizuno-group/ai-agent-env/claude`, but the working tree copy was missing. The files were restored from the index so the planned Claude shim and hook migration have real source files.
- The shared hook set was incomplete. `check_login_node.py`, `check_pip_forbidden.py`, `check_sbatch_forbidden.py`, and `check_secret_read.py` have been added and wired into agent hook settings.
- Claude profile settings and agent skill directories were incomplete. `settings.assist.json`, `settings.experiment.json`, and per-agent skill directories now exist.
- Direct runtime modes previously behaved like dry-run. They now prepare a run directory, prompt, capsule file, `apptainer_exec.sh`, and `submit.sbatch`; Slurm submission only happens when `--submit` is explicitly passed.
- Auth binds can hide files under `/home/sandbox/.claude`, `.codex`, or `.gemini`. `agentrun` now adds explicit read-only home config mounts after auth mounts so the config source of truth remains separate from auth metadata.
- `install.sh` now points Claude hooks at `common/hooks` and Claude skills at `agents/claude/skills`; the old `claude/` directory remains as the migrated legacy source.
- The login-node entrypoint was Python-only, which conflicts with clusters where Python must not run on login nodes. A shell entrypoint now exists at `runtime/agentrun/agentrun`; `install.sh` links that command to `$HOME/.local/bin/agentrun` only when `--apply` is explicitly used.
- The shell entrypoint now carries review-specific options into the capsule prompt and uses Antigravity command fallback order `agy`, `antigravity`, then `gemini`.
- `doctor.sh` still invoked the Python entrypoint. It now delegates to the shell entrypoint.
- The shell entrypoint now includes `smoke-test`, `verify-run`, stronger `validate`, image/writable/GPU checks in `doctor`, and non-zero exit status on failed doctor checks.
- The duplicate Python `agentrun` implementation was removed. The shell entrypoint is the only supported `agentrun` implementation.
- Run layout generation now creates standard live ledger files, artifact placeholders, and review placeholders required by the observability and run-ledger sections.
- Supervisor primitives now append events, create heartbeat/status/current-task files, capture stdout/stderr for supervised processes, check required outputs, and include walltime/disk-budget enforcement hooks.
- Shell `validate` now checks required profile sections, hook executability, and broken symlinks. Shell `doctor` now checks Git repository, current branch, and dirty worktree state in addition to host tools and image/run-dir readiness.
- Shell `dry-run` now prints selected profile/agent, host run directory, Slurm command, Apptainer command, bind mounts, generated capsule metadata, generated prompt, and expected artifacts.
- Product Slurm generation no longer embeds site-specific partition names. Runtime commands accept `--partition` or `AGENTRUN_SLURM_PARTITION`; creator partitions remain limited to test inputs and `tests/slurm/`.
- Shell `smoke-test` now prepares a Slurm submit script that writes the live ledger and required artifacts from a compute-node job instead of reporting local success on the login node.
- Shell `validate` now uses `jq` for JSON settings/hooks validation and shell-level TOML shape checks. Shell `verify-run` now checks JSON/JSONL parseability, status values, and exit/slurm metadata files.
- Generated Slurm scripts now record `SLURM_JOB_ID`, sorted environment, Apptainer version, and final exit code into the run ledger.
- Shell resource defaults now match the profile intent, including the lower-memory `review` profile.
- Shell `verify-run` logic now checks profile-specific required outputs, non-empty `artifacts/report.md`, final status values, and exit/slurm metadata.
- Run layout generation now includes `reviews/review_findings.json` for review mode outputs.
- `runtime/agentrun/templates/*.j2` now reflects the same ledger and profile-output expectations as the shell/Python generators.
- Apptainer image builds now use `--disable-cache` and do not set repository-local `APPTAINER_CACHEDIR` or `APPTAINER_TMPDIR`. Existing SIF files are reused unless their definition file is newer.
- The creator SIF build completed on Slurm and produced both `runtime/apptainer/base-system.sif` and `runtime/apptainer/base-agent.sif`.
- The creator agent CLI smoke completed successfully for Antigravity (`agy`), Codex, and Claude in job array `3305`.
- `agentrun smoke-test --submit` completed in Slurm job `3309`, and `agentrun verify-run .agent-runs/latest` passed.
- Codex auth staging now mirrors the Claude staging approach: `auth.json` is copied into the run home only on `--submit`, compute nodes do not bind `$HOME/.codex`, and the generated Slurm cleanup removes staged auth. The authenticated Codex smoke completed in Slurm job `3395`.

## Fixes Applied 2026-06-11

- `agents/claude/CLAUDE.md` uses `@`-import paths relative to the file's repo location
  (`@../../common/AGENTS.md`, `@../../claude/CLAUDE.md`). When bind-mounted to
  `/home/sandbox/.claude/CLAUDE.md` inside Apptainer these would resolve to
  `/home/sandbox/common/AGENTS.md`, which does not exist. `agentrun` now generates
  `.agent-runs/<run_id>/container_config/CLAUDE.md` with container-absolute paths
  (`@/home/sandbox/ai-agent-config/...`) and bind-mounts that file over the auth bind.
- `home_config_mounts()` previously always bound `agents/claude/settings.json` regardless
  of the run mode. It now uses the container_config copy, which is selected by mode:
  `settings.assist.json` for `assist`, `settings.experiment.json` for `experiment`,
  `settings.json` otherwise.
- `install.sh --apply` previously symlinked `agents/claude/CLAUDE.md` to
  `$HOME/.claude/CLAUDE.md`, which would also break `@`-imports on the host (host path ≠
  container path). It now generates `$HOME/.claude/CLAUDE.md` with host-absolute paths
  via `sed` substitution instead. `settings.json`, `hooks`, and `skills` remain symlinks.
- `README.md` and `docs/operations-ja.md` now document that `install.sh --apply` is not
  required for container use, and explain the "generated bind" pattern for config injection.

## Remaining Gaps Before Full Design Completion

- `assist`, `experiment`, `campaign`, `review`, and `multi-review` now prepare run directories and Slurm submission scripts. Full real-agent Slurm execution remains gated behind `--submit` and should be exercised per workflow.
- `agentrun validate` now performs shell-level profile shape checks; full YAML schema validation still needs an approved Python-capable environment or a non-Python validator.
- `agentrun doctor` checks common host tools, image presence, writable run directory, optional GPU visibility, and Git state. It reports Apptainer and uv as warnings when they are provided only on compute nodes or inside the image.
- `smoke-test --submit` now runs a short Slurm ledger/artifact smoke job. It does not yet invoke the real agent CLI through Apptainer; the separate `tests/slurm/agent-cli-smoke.sbatch` remains the cluster-side agent CLI smoke.
- The shell entrypoint covers login-node-safe plan generation and deterministic Slurm smoke submission.
- Supervisor and command broker files now contain reusable primitives, but Slurm/Apptainer process lifecycle wiring still needs approved-environment testing.
- Hooks need a shared schema and per-agent wiring review before being treated as complete.
- `install.sh --apply` still needs a user-approved run before global symlinks are changed.

## Implementation Plan From Here

1. Finish static implementation of the command layer without running Python on the login node.
2. Keep all mutating host setup behind explicit flags: `install.sh --apply` and `build-images.sh --run`.
3. Expand `agentrun` plan generation so it emits all commands, mounts, prompt text, and expected artifacts needed for human review.
4. Defer execution tests until the user approves running them in the correct environment.
5. Stop before running Slurm jobs, Apptainer builds, or agent CLI smoke tests on the login node.

## Tests Not Run Yet

The following tests were run:

- `./runtime/agentrun/agentrun validate`
- `./runtime/agentrun/agentrun doctor --all`
- Slurm SIF build via `tests/slurm/submit_creator_tests.sh build`
- Slurm agent CLI smoke via `tests/slurm/submit_creator_tests.sh agents`
- `./runtime/agentrun/agentrun smoke-test --agent claude --partition small-creator --time 00:05:00 --mem 4000M --submit`
- `./runtime/agentrun/agentrun verify-run .agent-runs/latest`

The duplicate non-shell implementation has been removed, so the shell `agentrun` checks above are the complete runtime check set.
