"""Codex adapter."""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AuthPath, ConfigPath


ROOT = Path(__file__).resolve().parents[3]

adapter = AgentAdapter(
    name="codex",
    role="secondary",
    command_candidates=("codex",),
    auth_paths=(
        AuthPath(Path.home() / ".codex" / "auth.json", "/home/sandbox/.codex/auth.json", required=False, writable=True),
    ),
    config_paths=(
        ConfigPath(ROOT / "agents" / "codex" / "AGENTS.md", "/home/sandbox/ai-agent-config/agents/codex/AGENTS.md"),
        ConfigPath(ROOT / "agents" / "codex" / "config.toml", "/home/sandbox/ai-agent-config/agents/codex/config.toml"),
    ),
)
