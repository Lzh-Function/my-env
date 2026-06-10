#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN=0
if [ "${1:-}" = "--run" ]; then
    RUN=1
fi

printf 'apptainer build base-system.sif base-system.def\n'
printf 'apptainer build base-agent.sif base-agent.def\n'

if [ "$RUN" -ne 1 ]; then
    printf 'dry-run complete; rerun inside a Slurm allocation with --run to build images\n'
    exit 0
fi

if [ -z "${SLURM_JOB_ID:-}" ]; then
    printf 'error: refusing to build images outside a Slurm allocation\n' >&2
    exit 2
fi

apptainer build base-system.sif base-system.def
apptainer build base-agent.sif base-agent.def

printf 'built %s/base-system.sif\n' "$SCRIPT_DIR"
printf 'built %s/base-agent.sif\n' "$SCRIPT_DIR"
