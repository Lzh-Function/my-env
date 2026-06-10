# AI Agent Environment

This directory is the configuration source of truth for the mizuno-group AI agent runtime.

It keeps shared agent rules, tool-specific shims, runtime profiles, hook sources, and a small `agentrun` launcher scaffold. Authentication state is intentionally not stored here.

## Layout

- `common/AGENTS.md`: shared rules for all agents.
- `claude/`: existing Claude Code configuration and hooks.
- `agents/`: tool-specific shims for Claude, Codex, and Antigravity.
- `profiles/`: runtime profiles for assist, experiment, campaign, review, and multi-review.
- `runtime/agentrun/`: login-node-safe shell launcher plus split Python runtime modules for later container-side validation.
- `runtime/apptainer/`: Apptainer definition templates.
- `tests/fixtures/`: smoke-test goal files and dummy repository fixtures.

## Safe Host Setup Preview

Symlink installation is dry-run by default:

```bash
./install.sh
./install.sh --apply
```

`install.sh` only creates symlinks under `$HOME` when `--apply` is passed.

Image build commands are also dry-run by default:

```bash
cd runtime/apptainer
./build-images.sh
```

Actual image builds must run inside a Slurm allocation:

```bash
./build-images.sh --run
```

## Login-Node-Safe Runtime Checks

Use the shell entrypoint on login nodes. It does not require Python:

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun doctor --all
./runtime/agentrun/agentrun dry-run assist --agent claude --repo . "Summarize this repository."
./runtime/agentrun/agentrun assist --agent claude --repo . "Prepare a run"
./runtime/agentrun/agentrun smoke-test --agent claude
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

Direct runtime modes prepare `.agent-runs/<run_id>/` and write `submit.sbatch`; they only submit when `--submit` is passed.

## Deferred Python Runtime Checks

The Python implementation is retained for later validation inside an approved runtime environment. Do not run it directly on login nodes where Python execution is forbidden:

```bash
./runtime/agentrun/agentrun.py validate
./runtime/agentrun/agentrun.py doctor --all
./runtime/agentrun/agentrun.py dry-run assist --agent claude --repo . "Summarize this repository."
```

The Python `smoke-test` is redundant with the shell smoke-test for login-node-safe use and should be deferred when Python is forbidden:

```bash
./runtime/agentrun/agentrun.py smoke-test --agent claude
./runtime/agentrun/agentrun.py verify-run .agent-runs/latest
```

Use this before wiring real Slurm and Apptainer execution.

## Building Images

`base-system.def` uses `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04` as the Docker base image.
