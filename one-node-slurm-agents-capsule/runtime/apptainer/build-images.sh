#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN=0
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --run)   RUN=1 ;;
        --force) FORCE=1 ;;
        system|all) ;; # Compatibility with the former two-image build.
        agent) printf 'warning: agent runtime is now part of base-system.sif; building system instead\n' >&2 ;;
        -h|--help)
            printf 'usage: build-images.sh [--run] [--force]\n'
            printf 'Legacy targets system, all, and agent all select the single system image.\n'
            exit 0 ;;
        *) printf 'usage: build-images.sh [--run] [--force]\n' >&2; exit 2 ;;
    esac
done

printf 'apptainer build --disable-cache base-system.sif base-system.def\n'

[ "$FORCE" -eq 0 ] || printf 'force rebuild enabled (target: system)\n'

if [ "$RUN" -ne 1 ]; then
    printf 'dry-run complete; rerun inside a Slurm allocation with --run to build images\n'
    exit 0
fi

if [ -z "${SLURM_JOB_ID:-}" ]; then
    printf 'error: refusing to build images outside a Slurm allocation\n' >&2
    exit 2
fi

if [ "$FORCE" -eq 0 ] && [ -e base-system.sif ] && [ base-system.sif -nt base-system.def ]; then
    printf 'reusing existing %s/base-system.sif\n' "$SCRIPT_DIR"
    exit 0
fi

tmp="base-system.${SLURM_JOB_ID}.sif"
trap 'rm -f "$tmp"' EXIT
apptainer build --disable-cache "$tmp" base-system.def
mv -f "$tmp" base-system.sif
trap - EXIT
printf 'built %s/base-system.sif\n' "$SCRIPT_DIR"
if [ "$FORCE" -eq 1 ] && { [ -e base-agent.sif ] || [ -L base-agent.sif ]; }; then
    rm -f -- base-agent.sif
    printf 'removed obsolete %s/base-agent.sif\n' "$SCRIPT_DIR"
fi
