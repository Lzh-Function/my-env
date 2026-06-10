"""Post-run verification helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .artifacts import PROFILE_REQUIRED_OUTPUTS, REQUIRED_OUTPUTS


@dataclass(frozen=True)
class VerifyResult:
    path: str
    ok: bool
    detail: str = ""


def verify_run(run_dir: Path) -> list[VerifyResult]:
    results: list[VerifyResult] = []
    for rel in REQUIRED_OUTPUTS:
        path = run_dir / rel
        results.append(VerifyResult(rel, path.exists(), "exists" if path.exists() else "missing"))
    report = run_dir / "artifacts" / "report.md"
    results.append(
        VerifyResult(
            "artifacts/report.md nonempty",
            report.exists() and bool(report.read_text(encoding="utf-8").strip()),
            "nonempty" if report.exists() and report.read_text(encoding="utf-8").strip() else "missing or empty",
        )
    )
    mode = ""
    capsule = run_dir / "capsule.yaml"
    if capsule.exists():
        for line in capsule.read_text(encoding="utf-8").splitlines():
            if line.startswith("mode:"):
                mode = line.split(":", 1)[1].strip()
                break
    profile_required = PROFILE_REQUIRED_OUTPUTS.get(mode)
    if profile_required is None:
        results.append(VerifyResult("profile required outputs", False, f"unknown mode: {mode or 'missing'}"))
    else:
        for rel in profile_required:
            path = run_dir / rel
            results.append(VerifyResult(f"profile_required:{rel}", path.exists(), "exists" if path.exists() else "missing"))
    for rel in ("live/exit_code.txt", "live/slurm_job_id.txt"):
        path = run_dir / rel
        results.append(VerifyResult(rel, path.exists(), "exists" if path.exists() else "missing"))
    status_path = run_dir / "live" / "status.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8")).get("status", "")
        except Exception as exc:
            results.append(VerifyResult("final_status", False, str(exc)))
        else:
            results.append(
                VerifyResult(
                    "final_status",
                    status in {"success", "failed", "cancelled", "timeout"},
                    status or "missing",
                )
            )
    return results
