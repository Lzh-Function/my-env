"""Policy helpers for agent capsule supervision."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ""


FORBIDDEN_COMMANDS = (
    r"(^|[;&|]\s*)sudo\b",
    r"(^|[;&|]\s*)apt(-get)?\b",
    r"(^|[;&|]\s*)pip(3)?\s+install\b",
    r"(^|[;&|]\s*)git\s+push\b",
    r"(^|[;&|]\s*)sbatch\b",
    r"(^|[;&|]\s*)salloc\b",
    r"(^|[;&|]\s*)ssh\b",
    r"(^|[;&|]\s*)cat\s+.*(\.ssh|id_rsa|id_ed25519|auth\.json|token|secret)",
)


def check_command(command: str) -> PolicyDecision:
    stripped = command.strip()
    if not stripped:
        return PolicyDecision(True)

    for pattern in FORBIDDEN_COMMANDS:
        if re.search(pattern, stripped, flags=re.IGNORECASE):
            return PolicyDecision(False, f"blocked by policy: {pattern}")

    return PolicyDecision(True)
