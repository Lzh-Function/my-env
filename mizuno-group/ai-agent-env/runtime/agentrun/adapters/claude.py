"""Claude Code adapter."""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AuthPath, ConfigPath


ROOT = Path(__file__).resolve().parents[3]

adapter = AgentAdapter(
    name="claude",
    role="secondary",
    command_candidates=("claude",),
    auth_paths=(),  # credentials are copied to run_dir/home at submit time
    config_paths=(
        ConfigPath(ROOT / "agents" / "claude" / "CLAUDE.md", "/home/sandbox/ai-agent-config/agents/claude/CLAUDE.md"),
        ConfigPath(ROOT / "claude" / "settings.json", "/home/sandbox/ai-agent-config/claude/settings.json"),
    ),
)
