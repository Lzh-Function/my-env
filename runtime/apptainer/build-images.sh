#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RUN=0
FORCE=0
TARGET=all

for arg in "$@"; do
    case "$arg" in
        --run)   RUN=1 ;;
        --force) FORCE=1 ;;
        system)  TARGET=system ;;
        agent)   TARGET=agent ;;
        *)       printf 'usage: build-images.sh [--run] [--force] [system|agent]\n' >&2; exit 2 ;;
    esac
done

# 通常は .def / 依存 .sif より古い image だけを作り直す。--force はこの判定を
# 無視して、指定した層を必ず作り直す。agent CLI は build 時に install script で
# 最新版を取得するため、.def を変えずに CLI を更新したいときに使う。
if [ "$FORCE" -eq 1 ]; then
    printf 'force: rebuilding %s regardless of existing images\n' \
        "$([ "$TARGET" = all ] && printf 'system and agent layers' || printf '%s layer' "$TARGET")"
fi

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

# localimage bootstrap は base-system.sif を unsquashfs でサンドボックスへ展開する。
# unsquashfs は cgroup ではなくノードの CPU 数で並列度を決める（48 コアなら 48 並列）
# ため、soft RLIMIT_NOFILE が 1024 のままだと展開途中で
# "FATAL ERROR: write_file: ... because Too many open files" で落ちる。
# soft を hard まで上げるのは非特権で可能。上げられなくてもビルドは続行する。
raise_nofile_limit() {
    local soft hard
    soft="$(ulimit -Sn)"
    hard="$(ulimit -Hn)"
    if [ "$hard" = "unlimited" ]; then
        hard=1048576
    fi
    if [ "$soft" != "unlimited" ] && [ "$soft" -lt "$hard" ] 2>/dev/null; then
        if ulimit -n "$hard" 2>/dev/null; then
            printf 'raised open file limit: %s -> %s\n' "$soft" "$(ulimit -Sn)"
        else
            printf 'warning: could not raise open file limit from %s; unsquashfs may fail with "Too many open files"\n' \
                "$soft" >&2
        fi
    fi
}

raise_nofile_limit

build_if_missing_or_stale() {
    local target="$1"
    local definition="$2"
    # 追加の依存（agent 層にとっての base-system.sif）。これを見ないと、
    # base-system.def だけ編集したときに system 層は再ビルドされるのに
    # agent 層が古いまま再利用され、変更が image に入らない。
    local dependency="${3:-}"
    local tmp="${target%.sif}.${SLURM_JOB_ID}.sif"

    if [ "$FORCE" -eq 1 ]; then
        printf 'rebuilding %s/%s: --force\n' "$SCRIPT_DIR" "$target"
    elif [ -e "$target" ] && [ "$target" -nt "$definition" ]; then
        if [ -z "$dependency" ] || { [ -e "$dependency" ] && [ "$target" -nt "$dependency" ]; }; then
            printf 'reusing existing %s/%s\n' "$SCRIPT_DIR" "$target"
            return 0
        fi
        printf 'rebuilding %s/%s: %s is newer\n' "$SCRIPT_DIR" "$target" "$dependency"
    fi

    # ビルドが途中で落ちると中途半端な $tmp が残り、再実行のたびに溜まっていく。
    if ! apptainer build --disable-cache "$tmp" "$definition"; then
        rm -f "$tmp"
        printf 'error: build failed for %s/%s\n' "$SCRIPT_DIR" "$target" >&2
        return 1
    fi
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
