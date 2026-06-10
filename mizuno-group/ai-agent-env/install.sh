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

link_file "$ROOT_DIR/agents/claude/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
link_file "$ROOT_DIR/agents/claude/settings.json" "$HOME/.claude/settings.json"
link_file "$ROOT_DIR/common/hooks" "$HOME/.claude/hooks"
link_file "$ROOT_DIR/agents/claude/skills" "$HOME/.claude/skills"

link_file "$ROOT_DIR/agents/codex/config.toml" "$HOME/.codex/config.toml"
link_file "$ROOT_DIR/agents/codex/hooks.json" "$HOME/.codex/hooks.json"
link_file "$ROOT_DIR/agents/codex/AGENTS.md" "$HOME/.codex/AGENTS.md"
link_file "$ROOT_DIR/agents/codex/skills" "$HOME/.agents/skills"

link_file "$ROOT_DIR/agents/antigravity/settings.json" "$HOME/.gemini/settings.json"
link_file "$ROOT_DIR/agents/antigravity/GEMINI.md" "$HOME/.gemini/GEMINI.md"
link_file "$ROOT_DIR/runtime/agentrun/agentrun" "$HOME/.local/bin/agentrun"

if [ "$APPLY" -eq 1 ]; then
    printf 'install complete\n'
else
    printf 'dry-run complete; rerun with --apply to create symlinks\n'
fi
