#!/usr/bin/env bash
set -euo pipefail

APPLY=0
if [ "${1:-}" = "--apply" ]; then
    APPLY=1
fi

for TARGET in "$HOME/.local/bin/agentrun" "${XDG_DATA_HOME:-$HOME/.local/share}/bash-completion/completions/agentrun"; do
    if [ "$APPLY" -eq 1 ]; then
        if [ -L "$TARGET" ] || [ -e "$TARGET" ]; then
            rm -f "$TARGET"
            printf 'removed %s\n' "$TARGET"
        else
            printf 'not found: %s\n' "$TARGET"
        fi
    else
        printf 'rm -f %s\n' "$TARGET"
    fi
done
if [ "$APPLY" -eq 1 ]; then
    printf 'uninstall complete\n'
else
    printf 'dry-run complete; rerun with --apply to remove\n'
fi
