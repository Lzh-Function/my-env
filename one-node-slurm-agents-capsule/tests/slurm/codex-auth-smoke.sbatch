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
IMAGE="$ENV_ROOT/runtime/apptainer/base-system.sif"
EXPECTED="OK_CODEX_AUTH_SMOKE_DONE"

cd "$ENV_ROOT"

mkdir -p "$RUN_DIR/home/.codex/skills"
cp "$ENV_ROOT/agents/codex/config.toml" "$RUN_DIR/home/.codex/config.toml"
for skill in "$ENV_ROOT"/common/skills/*; do
    [ -d "$skill" ] || continue
    ln -sfn "/home/sandbox/ai-agent-config/common/skills/$(basename "$skill")" \
        "$RUN_DIR/home/.codex/skills/$(basename "$skill")"
done

if [ ! -f "$RUN_DIR/home/.codex/auth.json" ]; then
    printf 'staged Codex auth file is missing: %s\n' "$RUN_DIR/home/.codex/auth.json" >&2
    exit 2
fi

cleanup_home() {
    rm -rf "$RUN_DIR/home"
}
trap cleanup_home EXIT

{
    printf 'job_id=%s\n' "${SLURM_JOB_ID:-}"
    printf 'node=%s\n' "${SLURMD_NODENAME:-}"
    printf 'agent=codex\n'
    printf 'started=%s\n' "$(date -Iseconds)"
} | tee "$RUN_DIR/live/job.env"

cat > "$RUN_DIR/prompt.txt" <<EOF
Use shell to run exactly this command once:
printf OK_CODEX_AUTH_SMOKE

After the command has run, reply with exactly this token and no extra text:
$EXPECTED
EOF

set +e
apptainer exec \
    --containall \
    --cleanenv \
    --bind "$ENV_ROOT/runtime/agentrun/install-agent.sh:/opt/agentrun/install-agent.sh:ro" \
    --home "$RUN_DIR/home:/home/sandbox" \
    --bind "$RUN_DIR/workspace:/workspace:rw" \
    --bind "$RUN_DIR:/runs:rw" \
    --bind "$RUN_DIR/scratch:/scratch:rw" \
    --bind "$RUN_DIR/cache:/cache:rw" \
    --bind "$ENV_ROOT/common/hooks:/home/sandbox/ai-agent-config/common/hooks:ro" \
    --bind "$ENV_ROOT/common/skills:/home/sandbox/ai-agent-config/common/skills:ro" \
    --bind "$ENV_ROOT/agents/codex/requirements.toml:/etc/codex/requirements.toml:ro" \
    --bind "$ENV_ROOT/agents/codex/AGENTS.md:/home/sandbox/.codex/AGENTS.md:ro" \
    --bind "$ENV_ROOT/agents/codex/rules:/home/sandbox/.codex/rules:ro" \
    "$IMAGE" \
    bash -lc 'agent_bin=$(bash /opt/agentrun/install-agent.sh codex) || exit $?; export PATH="$agent_bin:$PATH"; codex exec --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --skip-git-repo-check --cd /workspace "$(cat /runs/prompt.txt)"' \
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

if ! grep -q "OK_CODEX_AUTH_SMOKE" "$RUN_DIR/live/command_log.jsonl"; then
    printf '{"status":"failed","agent":"codex","reason":"managed hook did not record shell command"}\n' > "$RUN_DIR/live/status.json"
    printf 'managed Codex PostToolUse hook did not update %s\n' "$RUN_DIR/live/command_log.jsonl" >&2
    cat "$RUN_DIR/live/stdout.log" >&2
    cat "$RUN_DIR/live/stderr.log" >&2
    exit 1
fi

printf '{"status":"success","agent":"codex","mode":"auth-smoke","job_id":"%s"}\n' "${SLURM_JOB_ID:-}" > "$RUN_DIR/live/status.json"
printf '{"codex_auth_smoke":true,"status":"passed","agent":"codex","job_id":"%s"}\n' "${SLURM_JOB_ID:-}" > "$RUN_DIR/artifacts/metrics.json"
printf '# Codex Auth Smoke\n\nCodex returned the expected token through authenticated `codex exec`, and managed Codex hooks recorded the shell command.\n' > "$RUN_DIR/artifacts/report.md"
