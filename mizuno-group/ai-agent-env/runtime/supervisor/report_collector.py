"""Required-output verification helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_REQUIRED_OUTPUTS = (
    "live/status.json",
    "live/heartbeat.txt",
    "live/stdout.log",
    "live/stderr.log",
    "live/command_log.jsonl",
    "live/events.jsonl",
    "live/current_task.md",
    "artifacts/report.md",
    "artifacts/git_diff.patch",
    "artifacts/metrics.json",
)


@dataclass(frozen=True)
class OutputCheck:
    path: str
    exists: bool
    nonempty: bool


def check_outputs(run_dir: Path, required: tuple[str, ...] = DEFAULT_REQUIRED_OUTPUTS) -> list[OutputCheck]:
    checks: list[OutputCheck] = []
    for rel in required:
        path = run_dir / rel
        checks.append(OutputCheck(rel, path.exists(), path.exists() and path.stat().st_size > 0))
    return checks


def write_missing_artifact_placeholders(run_dir: Path) -> None:
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    defaults = {
        "git_diff.patch": "",
        "metrics.json": "{}\n",
        "environment.txt": "",
        "container.txt": "",
        "data_manifest.txt": "",
        "proposed_next.yaml": "",
        "proposed_train.sbatch": "",
    }
    for name, content in defaults.items():
        path = artifacts / name
        if not path.exists():
            path.write_text(content, encoding="utf-8")
