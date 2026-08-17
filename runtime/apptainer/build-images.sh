#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN=0
TARGET=all

for arg in "$@"; do
    case "$arg" in
        --run)   RUN=1 ;;
        system)  TARGET=system ;;
        agent)   TARGET=agent ;;
        *)       printf 'usage: build-images.sh [--run] [system|agent]\n' >&2; exit 2 ;;
    esac
done

case "$TARGET" in
    system) printf 'apptainer build --disable-cache base-system.sif base-system.def\n' ;;
    agent)  printf 'apptainer build --disable-cache base-agent.sif base-agent.def\n' ;;
    all)
        printf 'apptainer build --disable-cache base-system.sif base-system.def\n'
        printf 'apptainer build --disable-cache base-agent.sif base-agent.def\n'
        ;;
esac

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
    # 追加の依存（agent 層にとっての base-system.sif）。これを見ないと、
    # base-system.def だけ編集したときに system 層は再ビルドされるのに
    # agent 層が古いまま再利用され、変更が image に入らない。
    local dependency="${3:-}"
    local tmp="${target%.sif}.${SLURM_JOB_ID}.sif"

    if [ -e "$target" ] && [ "$target" -nt "$definition" ]; then
        if [ -z "$dependency" ] || { [ -e "$dependency" ] && [ "$target" -nt "$dependency" ]; }; then
            printf 'reusing existing %s/%s\n' "$SCRIPT_DIR" "$target"
            return 0
        fi
        printf 'rebuilding %s/%s: %s is newer\n' "$SCRIPT_DIR" "$target" "$dependency"
    fi

    apptainer build --disable-cache "$tmp" "$definition"
    mv -f "$tmp" "$target"
    printf 'built %s/%s\n' "$SCRIPT_DIR" "$target"
}

case "$TARGET" in
    system)
        build_if_missing_or_stale base-system.sif base-system.def
        ;;
    agent)
        if [ ! -e base-system.sif ]; then
            printf 'error: base-system.sif not found; build system first\n' >&2
            exit 2
        fi
        build_if_missing_or_stale base-agent.sif base-agent.def base-system.sif
        ;;
    all)
        build_if_missing_or_stale base-system.sif base-system.def
        build_if_missing_or_stale base-agent.sif base-agent.def base-system.sif
        ;;
esac
