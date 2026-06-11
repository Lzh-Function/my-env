"""Slurm command rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SlurmRequest:
    mode: str
    agent: str
    cpus: int
    memory: str
    time: str
    gpus: int = 0
    partition: str | None = None


def build_srun(request: SlurmRequest) -> list[str]:
    command = ["srun"]
    if request.partition:
        command.append(f"--partition={request.partition}")
    command.extend([f"--time={request.time}", f"--mem={request.memory}", f"--cpus-per-task={request.cpus}", "--pty"])
    if request.gpus > 0:
        command.append(f"--gres=gpu:{request.gpus}")
    return command


def render_sbatch(request: SlurmRequest, run_dir: str) -> str:
    lines = [
        "#!/usr/bin/env bash",
        f"#SBATCH --job-name=agentrun-{request.mode}-{request.agent}",
        f"#SBATCH --time={request.time}",
        f"#SBATCH --mem={request.memory}",
        f"#SBATCH --cpus-per-task={request.cpus}",
    ]
    if request.partition:
        lines.insert(2, f"#SBATCH --partition={request.partition}")
    if request.gpus > 0:
        lines.append(f"#SBATCH --gres=gpu:{request.gpus}")
    lines.extend(
        [
            f"#SBATCH --output={run_dir}/live/slurm.out",
            f"#SBATCH --error={run_dir}/live/slurm.err",
            "",
            "set -euo pipefail",
            f"printf '%s\\n' \"${{SLURM_JOB_ID:-}}\" > {run_dir}/live/slurm_job_id.txt",
            f"env | sort > {run_dir}/artifacts/environment.txt",
            f"apptainer --version > {run_dir}/artifacts/container.txt 2>/dev/null || true",
            "set +e",
            f"bash {run_dir}/apptainer_exec.sh",
            "rc=$?",
            "set -e",
            f"printf '%s\\n' \"$rc\" > {run_dir}/live/exit_code.txt",
            "exit \"$rc\"",
        ]
    )
    return "\n".join(lines)
