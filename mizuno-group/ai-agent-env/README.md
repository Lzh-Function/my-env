# AI Agent Environment

This directory is the configuration source of truth for the mizuno-group AI agent runtime.

It keeps shared agent rules, tool-specific shims, runtime profiles, hook sources, and a small `agentrun` launcher scaffold. Authentication state is intentionally not stored here.

For the current Japanese operations guide, including verified status, mount
layout, workspace visibility, and authentication binding, see
[`docs/operations-ja.md`](docs/operations-ja.md).

## Layout

- `common/AGENTS.md`: shared rules for all agents.
- `claude/`: existing Claude Code configuration and hooks.
- `agents/`: tool-specific shims for Claude, Codex, and Antigravity.
- `profiles/`: runtime profiles for assist, experiment, campaign, review, and multi-review.
- `runtime/agentrun/`: login-node-safe shell launcher plus split Python runtime modules for later container-side validation.
- `runtime/apptainer/`: Apptainer definition templates.
- `tests/fixtures/`: smoke-test goal files and dummy repository fixtures.

## Config Injection: Container vs Host

**Container use (primary)** — `install.sh --apply` is NOT required.
When `agentrun` prepares a run, it generates container-specific config under
`.agent-runs/<run_id>/container_config/` and bind-mounts those files directly
into the container. Claude and Codex authentication files are staged into the
run home only when `--submit` is used, so compute nodes do not need to see the login-node
`$HOME`; staged secrets are removed by the generated Slurm cleanup trap. The
host `$HOME` is never modified.

**Host direct use (optional)** — run `install.sh --apply` once to place
config symlinks and a generated `$HOME/.claude/CLAUDE.md` (with host-absolute
`@`-import paths). Use this only when you need `claude` / `agy` / `codex`
directly on the login node outside a container.

## Safe Host Setup Preview

Symlink installation is dry-run by default:

```bash
./install.sh
./install.sh --apply
```

`install.sh` only creates symlinks (and a generated CLAUDE.md) under `$HOME`
when `--apply` is passed.

Image build commands are also dry-run by default:

```bash
cd runtime/apptainer
./build-images.sh
```

Actual image builds must run inside a Slurm allocation:

```bash
./build-images.sh --run
```

The image build uses `apptainer build --disable-cache` and does not set
`APPTAINER_CACHEDIR` or `APPTAINER_TMPDIR` under the repository. Existing SIF
files are reused when they are newer than their definition files.

## Login-Node-Safe Runtime Checks

Use the shell entrypoint on login nodes. It does not require Python:

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun doctor --all
./runtime/agentrun/agentrun dry-run assist --agent claude --repo . "Summarize this repository."
./runtime/agentrun/agentrun assist --agent claude --repo . "Prepare a run"
./runtime/agentrun/agentrun smoke-test --agent claude --partition small-creator
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

Direct runtime modes prepare `.agent-runs/<run_id>/` and write `submit.sbatch`; they only submit when `--submit` is passed. Product runtime scripts do not embed a cluster partition. Pass `--partition` for tests or set `AGENTRUN_SLURM_PARTITION` when the site requires one.

## Deferred Python Runtime Checks

The Python implementation is retained for later validation inside an approved runtime environment. Do not run it directly on login nodes where Python execution is forbidden:

```bash
./runtime/agentrun/agentrun.py validate
./runtime/agentrun/agentrun.py doctor --all
./runtime/agentrun/agentrun.py dry-run assist --agent claude --repo . "Summarize this repository."
```

The Python runtime is redundant with the shell entrypoint for login-node-safe use and should be deferred when Python is forbidden:

```bash
./runtime/agentrun/agentrun.py smoke-test --agent claude
./runtime/agentrun/agentrun.py verify-run .agent-runs/latest
```

Use this before wiring real Slurm and Apptainer execution.

## Building Images

`base-system.def` uses `nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04` as the Docker base image.
