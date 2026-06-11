#!/usr/bin/env bash
#SBATCH --job-name=ai-agent-codex-auth-smoke
#SBATCH --partition=small-creator
#SBATCH --time=00:15:00
#SBATCH --mem=16000M
#SBATCH --cpus-per-task=2
#SBATCH --output=.agent-runs/creator-codex-auth-smoke/%j.out
#SBATCH --error=.agent-runs/creator-codex-auth-smoke/%j.err

set -euo pipefail

ENV_ROOT="${AI_AGENT_ENV_DIR:?AI_AGENT_ENV_DIR must be exported by submit_creator_tests.sh}"
RUN_DIR="${CODEX_AUTH_SMOKE_RUN_DIR:?CODEX_AUTH_SMOKE_RUN_DIR must be exported by submit_creator_tests.sh}"
IMAGE="$ENV_ROOT/runtime/apptainer/base-agent.sif"
EXPECTED="OK_CODEX_AUTH_SMOKE"

cd "$ENV_ROOT"

mkdir -p "$RUN_DIR/home/.codex/skills"
for skill in "$ENV_ROOT"/common/skills/*; do
    [ -d "$skill" ] || continue
    ln -sfn "/home/sandbox/ai-agent-config/common/skills/$(basename "$skill")" \
        "$RUN_DIR/home/.codex/skills/$(basename "$skill")"
done

if [ ! -f "$RUN_DIR/home/.codex/auth.json" ]; then
    printf 'staged Codex auth file is missing: %s\n' "$RUN_DIR/home/.codex/auth.json" >&2
    exit 2
fi

cleanup_auth() {
    rm -f "$RUN_DIR/home/.codex/auth.json"
}
trap cleanup_auth EXIT

{
    printf 'job_id=%s\n' "${SLURM_JOB_ID:-}"
    printf 'node=%s\n' "${SLURMD_NODENAME:-}"
    printf 'agent=codex\n'
    printf 'started=%s\n' "$(date -Iseconds)"
} | tee "$RUN_DIR/live/job.env"

cat > "$RUN_DIR/prompt.txt" <<EOF
Reply with exactly this token and no extra text:
$EXPECTED
EOF

set +e
apptainer exec \
    --containall \
    --cleanenv \
    --home "$RUN_DIR/home:/home/sandbox" \
    --bind "$RUN_DIR/workspace:/workspace:rw" \
    --bind "$RUN_DIR:/runs:rw" \
    --bind "$RUN_DIR/scratch:/scratch:rw" \
    --bind "$RUN_DIR/cache:/cache:rw" \
    --bind "$ENV_ROOT:/home/sandbox/ai-agent-config:ro" \
    --bind "$ENV_ROOT/agents/codex/config.toml:/home/sandbox/.codex/config.toml:ro" \
    --bind "$ENV_ROOT/agents/codex/hooks.json:/home/sandbox/.codex/hooks.json:ro" \
    --bind "$ENV_ROOT/agents/codex/AGENTS.md:/home/sandbox/.codex/AGENTS.md:ro" \
    --bind "$ENV_ROOT/agents/codex/rules:/home/sandbox/.codex/rules:ro" \
    "$IMAGE" \
    bash -lc 'codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --cd /workspace "$(cat /runs/prompt.txt)"' \
    > "$RUN_DIR/live/stdout.log" \
    2> "$RUN_DIR/live/stderr.log"
RC=$?
set -e

printf '%s\n' "$RC" > "$RUN_DIR/live/exit_code.txt"
printf 'finished=%s\n' "$(date -Iseconds)" | tee -a "$RUN_DIR/live/job.env"

if [ "$RC" -ne 0 ]; then
    printf '{"status":"failed","agent":"codex","exit_code":%s}\n' "$RC" > "$RUN_DIR/live/status.json"
    printf 'Codex auth smoke failed with exit code %s\n' "$RC" >&2
    exit "$RC"
fi

if ! grep -q "$EXPECTED" "$RUN_DIR/live/stdout.log"; then
    printf '{"status":"failed","agent":"codex","reason":"expected token missing"}\n' > "$RUN_DIR/live/status.json"
    printf 'expected token %s was not found in Codex stdout\n' "$EXPECTED" >&2
    exit 1
fi

printf '{"status":"success","agent":"codex","mode":"auth-smoke","job_id":"%s"}\n' "${SLURM_JOB_ID:-}" > "$RUN_DIR/live/status.json"
printf '{"codex_auth_smoke":true,"status":"passed","agent":"codex","job_id":"%s"}\n' "${SLURM_JOB_ID:-}" > "$RUN_DIR/artifacts/metrics.json"
printf '# Codex Auth Smoke\n\nCodex returned the expected token through authenticated `codex exec`.\n' > "$RUN_DIR/artifacts/report.md"
