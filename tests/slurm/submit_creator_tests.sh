#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
    build|agents|codex-auth|assist-pty|codex-assist-pty) MODE="$1" ;;
    *)
        printf 'usage: %s build|agents|codex-auth|assist-pty|codex-assist-pty\n' "$0" >&2
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
mkdir -p .agent-runs/creator-build-sif .agent-runs/creator-agent-smoke .agent-runs/creator-codex-auth-smoke .agent-runs/assist-pty-smoke .agent-runs/codex-assist-pty-smoke

case "$MODE" in
    build)
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" tests/slurm/build-sif.sbatch
        ;;
    agents)
        if [ ! -e runtime/apptainer/base-system.sif ]; then
            printf 'error: runtime/apptainer/base-system.sif is missing; run "%s build" first\n' "$0" >&2
            exit 2
        fi
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" --array=0-2 tests/slurm/agent-cli-smoke.sbatch
        ;;
    codex-auth)
        if [ ! -e runtime/apptainer/base-system.sif ]; then
            printf 'error: runtime/apptainer/base-system.sif is missing; run "%s build" first\n' "$0" >&2
            exit 2
        fi
        if [ ! -f "$HOME/.codex/auth.json" ]; then
            printf 'error: %s is missing; log in to Codex on the login node first\n' "$HOME/.codex/auth.json" >&2
            exit 2
        fi
        RUN_ID="$(date +%Y%m%d_%H%M%S_codex_auth_smoke)"
        RUN_DIR="$ENV_ROOT/.agent-runs/creator-codex-auth-smoke/$RUN_ID"
        mkdir -p "$RUN_DIR/home/.codex" "$RUN_DIR/live" "$RUN_DIR/artifacts" "$RUN_DIR/workspace" "$RUN_DIR/scratch" "$RUN_DIR/cache"
        cp "$HOME/.codex/auth.json" "$RUN_DIR/home/.codex/auth.json"
        chmod 600 "$RUN_DIR/home/.codex/auth.json"
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT",CODEX_AUTH_SMOKE_RUN_DIR="$RUN_DIR" tests/slurm/codex-auth-smoke.sbatch
        ;;
    assist-pty)
        if [ ! -e runtime/apptainer/base-system.sif ]; then
            printf 'error: runtime/apptainer/base-system.sif is missing; run "%s build" first\n' "$0" >&2
            exit 2
        fi
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" tests/slurm/assist-pty-smoke.sbatch
        ;;
    codex-assist-pty)
        if [ ! -e runtime/apptainer/base-system.sif ]; then
            printf 'error: runtime/apptainer/base-system.sif is missing; run "%s build" first\n' "$0" >&2
            exit 2
        fi
        sbatch --export=ALL,AI_AGENT_ENV_DIR="$ENV_ROOT" tests/slurm/codex-assist-pty-smoke.sbatch
        ;;
esac
