"""Available agent adapters."""

from __future__ import annotations

from .antigravity import adapter as antigravity
from .claude import adapter as claude
from .codex import adapter as codex


ADAPTERS = {
    "antigravity": antigravity,
    "claude": claude,
    "codex": codex,
}


def get_adapter(name: str):
    return ADAPTERS[name]
