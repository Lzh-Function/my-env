"""Apptainer command rendering helpers."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BindMount:
    host: Path
    container: str
    mode: str = "rw"

    def render(self) -> str:
        return f"{self.host}:{self.container}:{self.mode}"


def build_exec(image: Path, run_dir: Path, config_dir: Path, agent_command: list[str], binds: list[BindMount], gpus: int = 0) -> list[str]:
    command = ["apptainer", "exec"]
    if gpus > 0:
        command.append("--nv")
    command.extend(
        [
            "--containall",
            "--cleanenv",
            "--home",
            f"{run_dir / 'home'}:/home/sandbox",
            "--bind",
            f"{run_dir / 'workspace'}:/workspace:rw",
            "--bind",
            f"{run_dir}:/runs:rw",
            "--bind",
            f"{run_dir / 'scratch'}:/scratch:rw",
            "--bind",
            f"{run_dir / 'cache'}:/cache:rw",
            "--bind",
            f"{config_dir}:/home/sandbox/ai-agent-config:ro",
        ]
    )
    for bind in binds:
        command.extend(["--bind", bind.render()])
    command.extend([str(image), "bash", "-l", "-c", shlex.join(agent_command)])
    return command

