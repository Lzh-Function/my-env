"""Agent adapter definitions used by agentrun."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuthPath:
    host_path: Path
    container_path: str
    required: bool = False
    writable: bool = True


@dataclass(frozen=True)
class ConfigPath:
    host_path: Path
    container_path: str
    writable: bool = False


@dataclass(frozen=True)
class AgentAdapter:
    name: str
    role: str
    command_candidates: tuple[str, ...]
    auth_paths: tuple[AuthPath, ...]
    config_paths: tuple[ConfigPath, ...]

    def build_command(self, prompt_path: str, profile: str) -> list[str]:
        command = self.command_candidates[0]
        if self.name == "claude":
            return [command, "--print", "--dangerously-skip-permissions", prompt_path]
        if self.name == "codex":
            return [command, "exec", "--config", "/home/sandbox/ai-agent-config/agents/codex/config.toml", prompt_path]
        return [command, prompt_path]
