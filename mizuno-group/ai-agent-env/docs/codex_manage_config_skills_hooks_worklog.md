# Codex Config / Skills / Hooks Worklog

Date: 2026-06-12

## Current Codex Layout

- `common/codex/` no longer exists and is not part of the current design.
- `common/AGENTS.md` is the shared instruction source.
- `common/skills/` is the shared skills source.
- `common/hooks/` is the shared hook implementation source.
- `agents/codex/AGENTS.md` is a symlink to `../../common/AGENTS.md`.
- `agents/codex/skills` is a symlink to `../../common/skills`.
- `agents/codex/hooks.manifest.json` is the Codex hook source manifest.
- `agents/codex/hooks.json` is generated from the manifest in Codex's ordinary user-hook JSON shape for inspection and future compatibility.
- `agents/codex/requirements.toml` is generated from the same manifest and is the hook config consumed inside the container.
- `agents/codex/rules/` remains Codex-specific exec policy.

## Runtime Mounting

For Codex runs, `agentrun` now uses this shape:

- `$ROOT_DIR` is mounted read-only at `/home/sandbox/ai-agent-config`.
- The selected Codex `config*.toml` is copied into the run home at `/home/sandbox/.codex/config.toml`, so Codex can persist trust/config updates without writing to a read-only bind mount.
- `agents/codex/requirements.toml` is mounted read-only at `/etc/codex/requirements.toml`.
- `agents/codex/AGENTS.md` is mounted read-only at `/home/sandbox/.codex/AGENTS.md`.
- `agents/codex/rules` is mounted read-only at `/home/sandbox/.codex/rules`.
- `common/skills/*` is linked into the run home under `/home/sandbox/.codex/skills/*`.

The requirements file uses Codex managed hooks with:

```toml
[features]
hooks = true

[hooks]
managed_dir = "/home/sandbox/ai-agent-config/common/hooks"
```

Each active hook command points to the corresponding script under `common/hooks/`. This avoids relying on per-user hook trust state and makes the container run deterministic.

Codex launch commands still include `--dangerously-bypass-hook-trust` for both interactive `assist` and non-interactive `exec` paths. With managed hooks, trust is policy-controlled by `/etc/codex/requirements.toml`, but keeping the flag is harmless for the externally sandboxed SLURM + Apptainer use case and remains useful if a non-managed hook source is added later.

## Added Command

Added:

```bash
agentrun sync-codex
```

It performs the Codex-side common reflection step:

1. Validates `agents/codex/hooks.manifest.json`.
2. Verifies that every listed hook exists and is executable under `common/hooks/`.
3. Verifies that every `common/hooks/*.py` file is classified as `pre_command`, `post_command`, or `ignored`.
4. Regenerates `agents/codex/hooks.json` in Codex's ordinary `hooks.PreToolUse` / `hooks.PostToolUse` JSON shape.
5. Regenerates `agents/codex/requirements.toml` in Codex managed-hook TOML shape for `/etc/codex/requirements.toml`.
6. Refreshes `agents/codex/AGENTS.md -> ../../common/AGENTS.md`.
7. Refreshes `agents/codex/skills -> ../../common/skills`.

`agentrun validate` now checks that both `agents/codex/hooks.json` and `agents/codex/requirements.toml` are generated from the manifest and no longer expects the removed `common/codex/hooks.json`.

## Important Limitation

Skills and `AGENTS.md` changes are fully reflected through symlinks and run-home linking.

Hook script content changes are also reflected because `requirements.toml` points to scripts under `common/hooks/` via `/home/sandbox/ai-agent-config/common/hooks`.

Adding or removing a hook that should be active for Codex still requires updating `agents/codex/hooks.manifest.json` and then running `agentrun sync-codex`. This is intentional for now: `common/hooks/` contains hooks for multiple event models, including Claude-specific notification/session hooks, and Codex currently uses explicit `pre_command` / `post_command` hook phases. Auto-enabling every common hook for Codex would be unsafe without shared hook metadata that declares compatible agents and phases.

To prevent silent drift, `agentrun validate` fails when a new common hook is not classified in the Codex manifest. That forces Codex to explicitly decide whether the hook is active or ignored.

## Verification

Commands run:

```bash
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
python3 -m py_compile runtime/agentrun/agentrun.py runtime/agentrun/*.py runtime/agentrun/adapters/*.py
bash -n runtime/agentrun/agentrun tests/slurm/codex-assist-pty-smoke.sbatch tests/slurm/codex-auth-smoke.sbatch
python3 runtime/agentrun/agentrun.py validate
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator 'こんにちは'
./runtime/agentrun/agentrun dry-run assist --agent codex --submit --partition small-creator 'こんにちは'
tests/slurm/submit_creator_tests.sh codex-assist-pty
tests/slurm/submit_creator_tests.sh codex-auth
```

Results:

- `agentrun validate` passed.
- Python compile passed after fixing a pre-existing syntax error in `runtime/agentrun/prompt.py`.
- Python `agentrun.py validate` passed.
- Dry-run output shows Codex interactive assist uses top-level `codex` with `--dangerously-bypass-hook-trust`.
- Dry-run output shows `assist --submit` uses `codex exec` with `--dangerously-bypass-hook-trust`.
- Slurm `codex-assist-pty` job `3536` passed and verified that `/etc/codex/requirements.toml`, `AGENTS.md`, `rules`, and common skills are visible inside the container.
- Slurm `codex-auth` job `3537` passed. It authenticated Codex, forced a shell command (`printf OK_CODEX_AUTH_SMOKE`), and verified that managed `PostToolUse` wrote the command event to `/runs/live/command_log.jsonl`.
- In job `3537`, Codex stderr showed `hook: PreToolUse`, `hook: PostToolUse`, and completed hook entries.

## Native Hook Execution Audit

Official Codex hook documentation says hooks are loaded from `hooks.json` or inline `[hooks]` tables and organized under events such as `PreToolUse` and `PostToolUse`. It also notes that the newer `unified_exec` shell mechanism has incomplete interception for `PreToolUse` / `PostToolUse`.

After correcting the generated `hooks.json` shape, the following execution smokes were run on `small-creator`:

- `.agent-runs/codex-hook-smoke-20260612_195714`: official `hooks.PreToolUse` / `hooks.PostToolUse` shape with matcher `^Bash$`; Codex ran `printf HOOK_SMOKE`, but `/runs/live/command_log.jsonl` stayed empty.
- `.agent-runs/codex-hook-smoke-20260612_195908`: same official shape with matcher omitted; Codex ran `printf HOOK_SMOKE`, but `/runs/live/command_log.jsonl` stayed empty.
- `.agent-runs/codex-native-hook-smoke-20260612_200448`: used `--sandbox danger-full-access` instead of `--dangerously-bypass-approvals-and-sandbox`; Codex ran `printf HOOK_SMOKE`, but `/runs/live/command_log.jsonl` stayed empty.
- `.agent-runs/codex-bashenv-smoke-20260612_200230` and `.agent-runs/codex-bashenv-smoke-20260612_200335`: a temporary `BASH_ENV` bridge could trigger around Codex shell snapshot setup commands, but did not intercept the actual `printf HOOK_SMOKE` command.

The ordinary `~/.codex/hooks.json` path did not fire in the non-interactive `codex exec` smokes above. However, Codex managed hooks delivered through `/etc/codex/requirements.toml` did fire in the same SLURM + Apptainer runtime.

Current conclusion: for this project, Codex hook application is now implemented through managed requirements rather than user hooks. This matches the containerized design better because the run owns `/etc/codex/requirements.toml`, the scripts remain centralized in `common/hooks/`, and no per-run trust persistence is required.

Remaining caveat: hook additions or removals still require classifying the hook in `agents/codex/hooks.manifest.json` and running `agentrun sync-codex`. `agentrun validate` fails if a `common/hooks/*.py` file is unclassified, so drift is explicit rather than silent.
