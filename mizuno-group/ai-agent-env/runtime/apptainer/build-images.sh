#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

RUN=0
if [ "${1:-}" = "--run" ]; then
    RUN=1
fi

printf 'apptainer build --disable-cache base-system.sif base-system.def\n'
printf 'apptainer build --disable-cache base-agent.sif base-agent.def\n'

if [ "$RUN" -ne 1 ]; then
    printf 'dry-run complete; rerun inside a Slurm allocation with --run to build images\n'
    exit 0
fi

if [ -z "${SLURM_JOB_ID:-}" ]; then
    printf 'error: refusing to build images outside a Slurm allocation\n' >&2
    exit 2
fi

build_if_missing_or_stale() {
    local target="$1"
    local definition="$2"
    local tmp="${target%.sif}.${SLURM_JOB_ID}.sif"

    if [ -e "$target" ] && [ "$target" -nt "$definition" ]; then
        printf 'reusing existing %s/%s\n' "$SCRIPT_DIR" "$target"
        return 0
    fi

    apptainer build --disable-cache "$tmp" "$definition"
    mv -f "$tmp" "$target"
}

build_if_missing_or_stale base-system.sif base-system.def
build_if_missing_or_stale base-agent.sif base-agent.def

printf 'built %s/base-system.sif\n' "$SCRIPT_DIR"
printf 'built %s/base-agent.sif\n' "$SCRIPT_DIR"
