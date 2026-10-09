# Creator Slurm Tests

These files are for cluster tests only. They intentionally use creator partitions, which must not be embedded in product runtime scripts.

Run from a checkout or worktree under `/workspace/filesrv01`:

```bash
cd /workspace/filesrv01/<user>/<path-to-repo>/mizuno-group/ai-agent-env
tests/slurm/submit_creator_tests.sh build
tests/slurm/submit_creator_tests.sh agents
tests/slurm/submit_creator_tests.sh codex-auth
tests/slurm/submit_creator_tests.sh codex-assist-pty
```

Expected flow:

1. `build` submits `build-sif.sbatch` to `large-creator` and creates `runtime/apptainer/base-system.sif`.
2. `agents` submits `agent-cli-smoke.sbatch` to `small-creator` as a 3-task array for `antigravity`, `codex`, and `claude`. The smoke checks verify non-interactive CLI startup, not authenticated model responses.
3. `codex-auth` stages `$HOME/.codex/auth.json` into the run home, submits `codex-auth-smoke.sbatch`, and verifies a minimal authenticated `codex exec` response.
4. `codex-assist-pty` verifies that Codex assist runs are planned with the interactive top-level `codex` command, mode-specific config, hooks, AGENTS.md, rules, and common skill links.
5. Logs and outputs are written under `.agent-runs/creator-build-sif/`, `.agent-runs/creator-agent-smoke/`, `.agent-runs/creator-codex-auth-smoke/`, and `.agent-runs/codex-assist-pty-smoke/`.

Do not submit these jobs from `/home`; creator jobs require `/workspace/filesrv01`.
