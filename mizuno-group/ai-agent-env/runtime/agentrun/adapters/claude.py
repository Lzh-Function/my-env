"""Claude Code adapter."""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AuthPath, ConfigPath


ROOT = Path(__file__).resolve().parents[3]

adapter = AgentAdapter(
    name="claude",
    role="secondary",
    command_candidates=("claude",),
    auth_paths=(
        AuthPath(Path.home() / ".claude", "/home/sandbox/.claude", required=False, writable=True),
        AuthPath(Path.home() / ".claude.json", "/home/sandbox/.claude.json", required=False, writable=True),
    ),
    config_paths=(
        ConfigPath(ROOT / "agents" / "claude" / "CLAUDE.md", "/home/sandbox/ai-agent-config/agents/claude/CLAUDE.md"),
        ConfigPath(ROOT / "claude" / "settings.json", "/home/sandbox/ai-agent-config/claude/settings.json"),
    ),
)
