"""Static validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ValidationResult:
    name: str
    ok: bool
    detail: str = ""


REQUIRED_PATHS = (
    "common/AGENTS.md",
    "agents/claude/CLAUDE.md",
    "agents/claude/settings.json",
    "agents/codex/AGENTS.md",
    "agents/codex/config.toml",
    "agents/antigravity/AGENTS.md",
    "agents/antigravity/GEMINI.md",
    "runtime/apptainer/base-system.def",
    "runtime/apptainer/base-agent.def",
)


def validate_required_paths(root: Path) -> list[ValidationResult]:
    return [ValidationResult(path, (root / path).exists()) for path in REQUIRED_PATHS]


def validate_executable_hooks(root: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    for directory in (root / "common" / "hooks", root / "claude" / "hooks"):
        if not directory.exists():
            continue
        for path in sorted(directory.iterdir()):
            if path.is_file():
                results.append(ValidationResult(str(path.relative_to(root)), path.stat().st_mode & 0o111 != 0, "must be executable"))
    return results

