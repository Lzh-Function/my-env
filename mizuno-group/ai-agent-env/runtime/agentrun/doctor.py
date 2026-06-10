"""Preflight check helpers."""

from __future__ import annotations

import shutil
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str = ""


def check_commands(commands: tuple[str, ...]) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for command in commands:
        found = shutil.which(command)
        checks.append(DoctorCheck(f"command:{command}", bool(found), found or "not found"))
    return checks


def check_image(root: Path) -> DoctorCheck:
    image = root / "runtime" / "apptainer" / "base-agent.sif"
    return DoctorCheck("image:base-agent.sif", image.exists(), str(image))


def check_run_root(path: Path) -> DoctorCheck:
    return DoctorCheck("run directory writable", path.exists() and path.is_dir() and os.access(path, os.W_OK), str(path / ".agent-runs"))
