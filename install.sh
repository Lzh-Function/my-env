#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPLY=0

if [ "${1:-}" = "--apply" ]; then
    APPLY=1
fi

link_file() {
    local source="$1"
    local target="$2"
    printf 'ln -sfn %s %s\n' "$source" "$target"
    if [ "$APPLY" -eq 1 ]; then
        mkdir -p "$(dirname "$target")"
        ln -sfn "$source" "$target"
    fi
}

link_file "$ROOT_DIR/runtime/agentrun/agentrun" "$HOME/.local/bin/agentrun"

# secrets/.env is gitignored; seed it from the template so the entries are ready to fill in.
if [ ! -e "$ROOT_DIR/secrets/.env" ]; then
    printf 'cp %s %s (chmod 600)\n' "$ROOT_DIR/secrets/.env.example" "$ROOT_DIR/secrets/.env"
    if [ "$APPLY" -eq 1 ]; then
        (umask 077 && cp "$ROOT_DIR/secrets/.env.example" "$ROOT_DIR/secrets/.env")
    fi
fi

if [ "$APPLY" -eq 1 ]; then
    printf 'install complete\n'
else
    printf 'dry-run complete; rerun with --apply to create symlinks\n'
fi
