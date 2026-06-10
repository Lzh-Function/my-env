# Creator Slurm Tests

These files are for cluster tests only. They intentionally use creator partitions, which must not be embedded in product runtime scripts.

Run from a checkout or worktree under `/workspace/filesrv01`:

```bash
cd /workspace/filesrv01/<user>/<path-to-repo>/mizuno-group/ai-agent-env
tests/slurm/submit_creator_tests.sh build
tests/slurm/submit_creator_tests.sh agents
```

Expected flow:

1. `build` submits `build-sif.sbatch` to `medium-creator` and creates `runtime/apptainer/base-system.sif` and `runtime/apptainer/base-agent.sif`.
2. `agents` submits `agent-cli-smoke.sbatch` to `small-creator` as a 3-task array for `antigravity`, `codex`, and `claude`.
3. Logs and outputs are written under `.agent-runs/creator-build-sif/` and `.agent-runs/creator-agent-smoke/`.

Do not submit these jobs from `/home`; creator jobs require `/workspace/filesrv01`.
