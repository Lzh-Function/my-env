#!/usr/bin/env bash
# Smoke test for Codex assist PTY planning. It verifies that agentrun generates
# an interactive Codex command for srun --pty without launching the TUI.
#SBATCH --job-name=ai-agent-codex-assist-pty-smoke
#SBATCH --partition=small-creator
#SBATCH --time=00:10:00
#SBATCH --mem=8000M
#SBATCH --cpus-per-task=1
#SBATCH --output=.agent-runs/codex-assist-pty-smoke/slurm.out
#SBATCH --error=.agent-runs/codex-assist-pty-smoke/slurm.err

set -euo pipefail

ENV_ROOT="${AI_AGENT_ENV_DIR:?AI_AGENT_ENV_DIR must be exported by submit_creator_tests.sh}"
cd "$ENV_ROOT"

SMOKE_DIR="$ENV_ROOT/.agent-runs/codex-assist-pty-smoke"
mkdir -p "$SMOKE_DIR"

# shellcheck source=runtime/agentrun/agentrun
source "$ENV_ROOT/runtime/agentrun/agentrun"

RUN_ID="$(run_id "assist" "codex")"
RUN_DIR="$ENV_ROOT/.agent-runs/$RUN_ID"

write_plan "assist" "codex" "." "" "0" "01:00:00" "Say hello from Codex." "$RUN_DIR" "small-creator" "interactive"
EXEC_SCRIPT="$RUN_DIR/apptainer_exec.sh"

if [ ! -f "$EXEC_SCRIPT" ]; then
    printf '[FAIL] apptainer_exec.sh not found\n' >&2
    exit 1
fi

NORMALIZED_EXEC="$(tr -d '\\' < "$EXEC_SCRIPT")"

if ! printf '%s\n' "$NORMALIZED_EXEC" | grep -q 'codex --dangerously-bypass-approvals-and-sandbox --cd /workspace'; then
    printf '[FAIL] Codex assist command is not interactive top-level codex\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

if printf '%s\n' "$NORMALIZED_EXEC" | grep -q 'codex exec'; then
    printf '[FAIL] Codex assist command still uses non-interactive codex exec\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

if grep -qF "/home/sandbox/.codex/config.toml:ro" "$EXEC_SCRIPT"; then
    printf '[FAIL] Codex assist config is still read-only bind-mounted\n' >&2
    cat "$EXEC_SCRIPT" >&2
    exit 1
fi

if ! cmp -s "$ENV_ROOT/agents/codex/config.assist.toml" "$RUN_DIR/home/.codex/config.toml"; then
    printf '[FAIL] Codex assist config does not match agents/codex/config.assist.toml\n' >&2
    exit 1
fi

for path in \
    "$ENV_ROOT/agents/codex/hooks.json:/home/sandbox/.codex/hooks.json:ro" \
    "$ENV_ROOT/agents/codex/AGENTS.md:/home/sandbox/.codex/AGENTS.md:ro" \
    "$ENV_ROOT/agents/codex/rules:/home/sandbox/.codex/rules:ro"
do
    if ! grep -qF "$path" "$EXEC_SCRIPT"; then
        printf '[FAIL] missing Codex config mount: %s\n' "$path" >&2
        cat "$EXEC_SCRIPT" >&2
        exit 1
    fi
done

if [ ! -L "$RUN_DIR/home/.codex/skills/work-log" ]; then
    printf '[FAIL] Codex common skill symlink was not created in run home\n' >&2
    find "$RUN_DIR/home/.codex" -maxdepth 3 -print >&2
    exit 1
fi

IMAGE="$ENV_ROOT/runtime/apptainer/base-agent.sif"
set +e
apptainer exec \
    --containall \
    --cleanenv \
    --home "$RUN_DIR/home:/home/sandbox" \
    --bind "$ENV_ROOT:/workspace:rw" \
    --bind "$RUN_DIR:/runs:rw" \
    --bind "$RUN_DIR/scratch:/scratch:rw" \
    --bind "$RUN_DIR/cache:/cache:rw" \
    --bind "$ENV_ROOT:/home/sandbox/ai-agent-config:ro" \
    --bind "$ENV_ROOT/agents/codex/hooks.json:/home/sandbox/.codex/hooks.json:ro" \
    --bind "$ENV_ROOT/agents/codex/AGENTS.md:/home/sandbox/.codex/AGENTS.md:ro" \
    --bind "$ENV_ROOT/agents/codex/rules:/home/sandbox/.codex/rules:ro" \
    "$IMAGE" \
    bash -lc '
        set -euo pipefail
        test -f /home/sandbox/.codex/config.toml
        test -w /home/sandbox/.codex/config.toml
        printf "\n# trust smoke write\n" >> /home/sandbox/.codex/config.toml
        test -f /home/sandbox/.codex/hooks.json
        test -f /home/sandbox/.codex/AGENTS.md
        test -d /home/sandbox/.codex/rules
        test -L /home/sandbox/.codex/skills/work-log
        test -e /home/sandbox/.codex/skills/work-log/SKILL.md
        grep -q "/home/sandbox/ai-agent-config/common/hooks/block_dangerous_command.py" /home/sandbox/.codex/hooks.json
        grep -q "BASE GUIDELINES" /home/sandbox/.codex/AGENTS.md
    ' \
    > "$RUN_DIR/live/container-config-check.out" \
    2> "$RUN_DIR/live/container-config-check.err"
RC=$?
set -e

if [ "$RC" -ne 0 ]; then
    printf '[FAIL] Codex config/common assets are not visible inside the container\n' >&2
    cat "$RUN_DIR/live/container-config-check.out" >&2
    cat "$RUN_DIR/live/container-config-check.err" >&2
    exit "$RC"
fi

BATCH_RUN_DIR="$ENV_ROOT/.agent-runs/$(run_id "assist-submit" "codex")"
write_plan "assist" "codex" "." "" "0" "01:00:00" "Say hello from submitted Codex." "$BATCH_RUN_DIR" "small-creator" "batch"
BATCH_EXEC_SCRIPT="$BATCH_RUN_DIR/apptainer_exec.sh"
BATCH_NORMALIZED_EXEC="$(tr -d '\\' < "$BATCH_EXEC_SCRIPT")"

if ! printf '%s\n' "$BATCH_NORMALIZED_EXEC" | grep -q 'codex exec --dangerously-bypass-approvals-and-sandbox'; then
    printf '[FAIL] Codex assist --submit plan does not use non-interactive codex exec\n' >&2
    cat "$BATCH_EXEC_SCRIPT" >&2
    exit 1
fi

if grep -qF "/home/sandbox/.codex/config.toml:ro" "$BATCH_EXEC_SCRIPT"; then
    printf '[FAIL] Codex assist --submit config is still read-only bind-mounted\n' >&2
    cat "$BATCH_EXEC_SCRIPT" >&2
    exit 1
fi

if printf '%s\n' "$BATCH_NORMALIZED_EXEC" | grep -q 'bash -l -c codex --dangerously'; then
    printf '[FAIL] Codex assist --submit plan still uses interactive top-level codex\n' >&2
    cat "$BATCH_EXEC_SCRIPT" >&2
    exit 1
fi

rm -rf "$RUN_DIR/home" "$BATCH_RUN_DIR/home"

printf '{"status":"success","test":"codex-assist-pty-smoke"}\n' > "$SMOKE_DIR/status.json"
printf '# Codex Assist PTY Smoke\n\nAll Codex assist interactive, assist-submit batch, and container config visibility checks passed.\n' > "$SMOKE_DIR/report.md"
printf '[OK] codex-assist-pty-smoke passed\n'
