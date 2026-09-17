#!/usr/bin/env bash
#SBATCH --job-name=ai-agent-cli-smoke
#SBATCH --partition=small-creator
#SBATCH --time=00:20:00
#SBATCH --mem=32000M
#SBATCH --cpus-per-task=2
#SBATCH --output=.agent-runs/creator-agent-smoke/%A_%a.out
#SBATCH --error=.agent-runs/creator-agent-smoke/%A_%a.err

set -euo pipefail

ENV_ROOT="${AI_AGENT_ENV_DIR:?AI_AGENT_ENV_DIR must be exported by submit_creator_tests.sh}"
cd "$ENV_ROOT"

AGENTS=(antigravity codex claude)
AGENT="${AGENTS[$SLURM_ARRAY_TASK_ID]}"
RUN_DIR="$ENV_ROOT/.agent-runs/creator-agent-smoke/${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${AGENT}"
IMAGE="$ENV_ROOT/runtime/apptainer/base-agent.sif"

mkdir -p \
    "$RUN_DIR/home/.claude" \
    "$RUN_DIR/home/.codex" \
    "$RUN_DIR/home/.gemini" \
    "$RUN_DIR/home/.antigravity" \
    "$RUN_DIR/live" \
    "$RUN_DIR/artifacts" \
    "$RUN_DIR/workspace" \
    "$RUN_DIR/scratch" \
    "$RUN_DIR/cache"

case "$AGENT" in
    claude)
        AGENT_COMMAND='claude --version'
        ;;
    codex)
        AGENT_COMMAND='codex --version'
        ;;
    antigravity)
        AGENT_COMMAND='if command -v agy >/dev/null 2>&1; then agy --help; elif command -v antigravity >/dev/null 2>&1; then antigravity --help; else gemini --help; fi'
        ;;
    *)
        printf 'unknown agent: %s\n' "$AGENT" >&2
        exit 2
        ;;
esac

{
    printf 'job_id=%s\n' "${SLURM_JOB_ID:-}"
    printf 'array_job_id=%s\n' "${SLURM_ARRAY_JOB_ID:-}"
    printf 'array_task_id=%s\n' "${SLURM_ARRAY_TASK_ID:-}"
    printf 'node=%s\n' "${SLURMD_NODENAME:-}"
    printf 'agent=%s\n' "$AGENT"
    printf 'started=%s\n' "$(date -Iseconds)"
} | tee "$RUN_DIR/live/job.env"

set +e
apptainer exec \
    --containall \
    --cleanenv \
    --home "$RUN_DIR/home:/home/sandbox" \
    --bind "$RUN_DIR/workspace:/workspace:rw" \
    --bind "$RUN_DIR:/runs:rw" \
    --bind "$RUN_DIR/scratch:/scratch:rw" \
    --bind "$RUN_DIR/cache:/cache:rw" \
    --bind "$ENV_ROOT/common/hooks:/home/sandbox/ai-agent-config/common/hooks:ro" \
    --bind "$ENV_ROOT/common/skills:/home/sandbox/ai-agent-config/common/skills:ro" \
    "$IMAGE" \
    bash -lc "$AGENT_COMMAND" \
    > "$RUN_DIR/live/stdout.log" \
    2> "$RUN_DIR/live/stderr.log"
RC=$?
set -e

printf '%s\n' "$RC" > "$RUN_DIR/live/exit_code.txt"
printf 'finished=%s\n' "$(date -Iseconds)" | tee -a "$RUN_DIR/live/job.env"

if [ "$RC" -ne 0 ]; then
    printf 'agent command failed with exit code %s\n' "$RC" >&2
    exit "$RC"
fi

if [ ! -s "$RUN_DIR/live/stdout.log" ] && [ ! -s "$RUN_DIR/live/stderr.log" ]; then
    printf 'agent command produced no output for %s\n' "$AGENT" >&2
    exit 1
fi

printf '{"status":"success","agent":"%s"}\n' "$AGENT" > "$RUN_DIR/live/status.json"
printf '# Agent CLI Smoke\n\nAgent `%s` CLI started successfully in the container.\n' "$AGENT" > "$RUN_DIR/artifacts/report.md"
