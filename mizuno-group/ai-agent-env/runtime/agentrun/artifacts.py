"""Run artifact requirements."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


REQUIRED_OUTPUTS = (
    "capsule.yaml",
    "prompt.txt",
    "goal.yaml",
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

PROFILE_REQUIRED_OUTPUTS = {
    "assist": (
        "live/status.json",
        "live/heartbeat.txt",
        "live/stdout.log",
        "live/stderr.log",
        "live/command_log.jsonl",
        "artifacts/report.md",
        "artifacts/git_diff.patch",
        "artifacts/metrics.json",
    ),
    "experiment": (
        "live/status.json",
        "live/heartbeat.txt",
        "live/stdout.log",
        "live/stderr.log",
        "live/command_log.jsonl",
        "live/current_task.md",
        "artifacts/report.md",
        "artifacts/git_diff.patch",
        "artifacts/metrics.json",
        "artifacts/proposed_next.yaml",
    ),
    "campaign": (
        "live/status.json",
        "live/heartbeat.txt",
        "artifacts/report.md",
        "artifacts/metrics.json",
        "artifacts/proposed_next.yaml",
        "artifacts/proposed_train.sbatch",
    ),
    "review": (
        "live/status.json",
        "live/stdout.log",
        "reviews/review_findings.json",
    ),
    "multi-review": (
        "live/status.json",
        "reviews/antigravity.md",
        "reviews/claude.md",
        "reviews/codex.md",
        "reviews/summary.md",
        "reviews/disagreements.json",
        "reviews/final_recommendation.md",
    ),
    "smoke-test": (
        "live/status.json",
        "live/heartbeat.txt",
        "live/stdout.log",
        "live/stderr.log",
        "live/command_log.jsonl",
        "artifacts/report.md",
        "artifacts/git_diff.patch",
        "artifacts/metrics.json",
    ),
}


@dataclass(frozen=True)
class ArtifactCheck:
    path: str
    exists: bool
    nonempty: bool


def check_required_outputs(run_dir: Path) -> list[ArtifactCheck]:
    checks: list[ArtifactCheck] = []
    for rel in REQUIRED_OUTPUTS:
        path = run_dir / rel
        checks.append(ArtifactCheck(rel, path.exists(), path.exists() and path.stat().st_size > 0))
    return checks
