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

# secrets/.env and secrets/gh.env are gitignored; seed them from their templates
# so the entries are ready to fill in.
for secrets_file in .env gh.env; do
    if [ ! -e "$ROOT_DIR/secrets/$secrets_file" ]; then
        printf 'cp %s %s (chmod 600)\n' "$ROOT_DIR/secrets/$secrets_file.example" "$ROOT_DIR/secrets/$secrets_file"
        if [ "$APPLY" -eq 1 ]; then
            (umask 077 && cp "$ROOT_DIR/secrets/$secrets_file.example" "$ROOT_DIR/secrets/$secrets_file")
        fi
    fi
done

if [ "$APPLY" -eq 1 ]; then
    printf 'install complete\n'
else
    printf 'dry-run complete; rerun with --apply to create symlinks\n'
fi
