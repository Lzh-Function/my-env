"""Antigravity adapter."""

from __future__ import annotations

from pathlib import Path

from .base import AgentAdapter, AuthPath, ConfigPath


ROOT = Path(__file__).resolve().parents[3]

adapter = AgentAdapter(
    name="antigravity",
    role="primary",
    command_candidates=("agy", "antigravity", "gemini"),
    auth_paths=(),  # credentials are copied to run_dir/home at submit time
    config_paths=(
        ConfigPath(ROOT / "agents" / "antigravity" / "AGENTS.md", "/home/sandbox/ai-agent-config/agents/antigravity/AGENTS.md"),
        ConfigPath(ROOT / "agents" / "antigravity" / "GEMINI.md", "/home/sandbox/ai-agent-config/agents/antigravity/GEMINI.md"),
    ),
)
