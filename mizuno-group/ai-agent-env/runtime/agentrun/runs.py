"""Run directory helpers."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path


RUN_SUBDIRS = (
    "live",
    "artifacts",
    "reviews",
    "workspace",
    "scratch",
    "cache",
    "home/.claude",
    "home/.codex",
    "home/.codex/skills",
    "home/.agents",
    "home/.gemini/antigravity-cli",
    "home/.antigravity",
)

LEDGER_PLACEHOLDERS = {
    "live/stdout.log": "",
    "live/stderr.log": "",
    "live/command_log.jsonl": "",
    "live/events.jsonl": "",
    "live/slurm.out": "",
    "live/slurm.err": "",
    "live/exit_code.txt": "",
    "live/slurm_job_id.txt": "",
    "live/current_task.md": "initialized\n",
    "live/status.json": "{}\n",
    "artifacts/git_diff.patch": "",
    "artifacts/metrics.json": "{}\n",
    "artifacts/environment.txt": "",
    "artifacts/container.txt": "",
    "artifacts/data_manifest.txt": "",
    "artifacts/proposed_next.yaml": "",
    "artifacts/proposed_train.sbatch": "",
    "reviews/claude.md": "",
    "reviews/codex.md": "",
    "reviews/antigravity.md": "",
    "reviews/review_findings.json": "{}\n",
    "reviews/summary.md": "",
    "reviews/disagreements.json": "{}\n",
    "reviews/final_recommendation.md": "",
}


def new_run_id(mode: str, agent: str) -> str:
    return datetime.now().strftime(f"%Y%m%d_%H%M%S_{mode}_{agent}")


def create_run_dir(root: Path, run_id: str) -> Path:
    run_dir = root / ".agent-runs" / run_id
    for rel in RUN_SUBDIRS:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)
    for rel, content in LEDGER_PLACEHOLDERS.items():
        path = run_dir / rel
        if not path.exists():
            path.write_text(content, encoding="utf-8")
    latest = run_dir.parent / "latest"
    if latest.exists() or latest.is_symlink():
        latest.unlink()
    latest.symlink_to(run_dir.name)
    return run_dir


def make_executable(path: Path) -> None:
    current = path.stat().st_mode
    os.chmod(path, current | 0o111)
