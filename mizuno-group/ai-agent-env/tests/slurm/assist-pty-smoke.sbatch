#!/usr/bin/env bash
# Smoke test for assist PTY mode: verifies that agentrun prepare + container
# launch works for claude with interactive (non --print) command.
#SBATCH --job-name=ai-agent-assist-pty-smoke
#SBATCH --partition=small-creator
#SBATCH --time=00:15:00
#SBATCH --mem=32000M
#SBATCH --cpus-per-task=4
#SBATCH --output=.agent-runs/assist-pty-smoke/slurm.out
#SBATCH --error=.agent-runs/assist-pty-smoke/slurm.err

set -euo pipefail

ENV_ROOT="${AI_AGENT_ENV_DIR:?AI_AGENT_ENV_DIR must be exported by submit_creator_tests.sh}"
cd "$ENV_ROOT"

IMAGE="$ENV_ROOT/runtime/apptainer/base-agent.sif"
SMOKE_DIR="$ENV_ROOT/.agent-runs/assist-pty-smoke"
mkdir -p "$SMOKE_DIR"

# --------------------------------------------------------------------------
# Step 1: source agentrun to access write_plan and verify internal functions
# --------------------------------------------------------------------------
# shellcheck source=runtime/agentrun/agentrun
source "$ENV_ROOT/runtime/agentrun/agentrun"

RUN_ID="$(run_id "assist" "claude")"
RUN_DIR="$ENV_ROOT/.agent-runs/$RUN_ID"

write_plan "assist" "claude" "." "" "0" "01:00:00" "Say hello world." "$RUN_DIR" "small-creator" "interactive"
printf '[OK] write_plan generated run directory: %s\n' "$RUN_DIR"

# --------------------------------------------------------------------------
# Step 2: Verify apptainer_exec.sh uses interactive claude (no --print flag)
# --------------------------------------------------------------------------
EXEC_SCRIPT="$RUN_DIR/apptainer_exec.sh"
if [ ! -f "$EXEC_SCRIPT" ]; then
    printf '[FAIL] apptainer_exec.sh not found\n' >&2
    exit 1
fi

if ! grep -q 'claude.*dangerously-skip-permissions' "$EXEC_SCRIPT"; then
    printf '[FAIL] apptainer_exec.sh does not contain interactive claude command\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

if grep -q -- '--print' "$EXEC_SCRIPT"; then
    printf '[FAIL] apptainer_exec.sh still contains --print flag (should be interactive)\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

printf '[OK] apptainer_exec.sh contains interactive claude command (no --print)\n'

# --------------------------------------------------------------------------
# Step 3: Verify CLAUDE.md bind-mount uses agents/claude/CLAUDE.md (symlink)
#         and NOT container_config/CLAUDE.md (old generated copy)
# --------------------------------------------------------------------------
if grep -qF "container_config/CLAUDE.md" "$EXEC_SCRIPT"; then
    printf '[FAIL] apptainer_exec.sh still references container_config/CLAUDE.md\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

if ! grep -qF "agents/claude/CLAUDE.md" "$EXEC_SCRIPT"; then
    printf '[FAIL] apptainer_exec.sh does not reference agents/claude/CLAUDE.md\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

printf '[OK] CLAUDE.md bind-mount points to agents/claude/CLAUDE.md (symlink to common/AGENTS.md)\n'

# --------------------------------------------------------------------------
# Step 4: Verify the container launches and claude --version works
#         This confirms PTY session would succeed in the same container
# --------------------------------------------------------------------------
printf '[INFO] Testing container startup with claude --version...\n'

mkdir -p "$RUN_DIR/home/.claude"
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
    --bind "$ENV_ROOT/agents/claude/CLAUDE.md:/home/sandbox/.claude/CLAUDE.md:ro" \
    --bind "$ENV_ROOT/agents/claude/settings.json:/home/sandbox/.claude/settings.json:ro" \
    --bind "$ENV_ROOT/common/hooks:/home/sandbox/.claude/hooks:ro" \
    --bind "$ENV_ROOT/agents/claude/skills:/home/sandbox/.claude/skills:ro" \
    "$IMAGE" \
    bash -l -c "claude --version" \
    > "$RUN_DIR/live/stdout.log" \
    2> "$RUN_DIR/live/stderr.log"
RC=$?
set -e

if [ "$RC" -ne 0 ]; then
    printf '[FAIL] claude --version failed (rc=%s)\n' "$RC" >&2
    cat "$RUN_DIR/live/stdout.log" >&2
    cat "$RUN_DIR/live/stderr.log" >&2
    exit "$RC"
fi

printf '[OK] claude --version succeeded inside container:\n'
cat "$RUN_DIR/live/stdout.log"

# --------------------------------------------------------------------------
# Step 5: Confirm srun --pty invocation that would be used in real assist run
# --------------------------------------------------------------------------
printf '[INFO] Expected srun invocation for interactive assist:\n'
printf '  srun --time=01:00:00 --mem=32000M --cpus-per-task=4 --pty --partition=small-creator %s\n' "$RUN_DIR/apptainer_exec.sh"
printf '[INFO] In a real terminal: agentrun assist --agent claude --partition small-creator "your prompt"\n'

printf '{"status":"success","test":"assist-pty-smoke"}\n' > "$SMOKE_DIR/status.json"
printf '# Assist PTY Smoke Test\n\nAll checks passed.\n\n- write_plan generates correct interactive command\n- CLAUDE.md bind-mount uses symlink path\n- Container launches and claude --version succeeds\n' > "$SMOKE_DIR/report.md"
printf '[OK] assist-pty-smoke passed\n'
