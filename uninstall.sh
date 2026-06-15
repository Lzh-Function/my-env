#!/usr/bin/env bash
set -euo pipefail

APPLY=0
if [ "${1:-}" = "--apply" ]; then
    APPLY=1
fi

TARGET="$HOME/.local/bin/agentrun"

if [ "$APPLY" -eq 1 ]; then
    if [ -L "$TARGET" ] || [ -e "$TARGET" ]; then
        rm -f "$TARGET"
        printf 'removed %s\n' "$TARGET"
    else
        printf 'not found: %s\n' "$TARGET"
    fi
    printf 'uninstall complete\n'
else
    printf 'rm -f %s\n' "$TARGET"
    printf 'dry-run complete; rerun with --apply to remove\n'
fi
