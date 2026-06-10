#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    build|agents) MODE="$1" ;;
    *)
        printf 'usage: %s build|agents\n' "$0" >&2
        exit 2
        ;;
esac

ENV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "$ENV_ROOT" in
    /workspace/filesrv01/*) ;;
    *)
        printf 'error: creator jobs must be submitted from /workspace/filesrv01; current ai-agent-env is %s\n' "$ENV_ROOT" >&2
        exit 2
        ;;
esac

cd "$ENV_ROOT"
mkdir -p .agent-runs/creator-build-sif .agent-runs/creator-agent-smoke

case "$MODE" in
    build)
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" tests/slurm/build-sif.sbatch
        ;;
    agents)
        if [ ! -e runtime/apptainer/base-agent.sif ]; then
            printf 'error: runtime/apptainer/base-agent.sif is missing; run "%s build" first\n' "$0" >&2
            exit 2
        fi
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" --array=0-2 tests/slurm/agent-cli-smoke.sbatch
        ;;
esac
