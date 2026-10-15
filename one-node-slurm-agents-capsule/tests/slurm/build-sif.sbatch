#!/usr/bin/env bash
#SBATCH --job-name=ai-agent-build-sif
#SBATCH --partition=large-creator
#SBATCH --time=04:00:00
#SBATCH --mem=120000M
#SBATCH --cpus-per-task=4
#SBATCH --output=.agent-runs/creator-build-sif/%j.out
#SBATCH --error=.agent-runs/creator-build-sif/%j.err

set -euo pipefail

ENV_ROOT="${AI_AGENT_ENV_DIR:?AI_AGENT_ENV_DIR must be exported by submit_creator_tests.sh}"
cd "$ENV_ROOT"

mkdir -p .agent-runs/creator-build-sif
{
    printf 'job_id=%s\n' "${SLURM_JOB_ID:-}"
    printf 'node=%s\n' "${SLURMD_NODENAME:-}"
    printf 'started=%s\n' "$(date -Iseconds)"
} | tee ".agent-runs/creator-build-sif/${SLURM_JOB_ID}.env"

command -v apptainer | tee ".agent-runs/creator-build-sif/${SLURM_JOB_ID}.apptainer.path"
apptainer --version | tee ".agent-runs/creator-build-sif/${SLURM_JOB_ID}.apptainer.version"

./runtime/apptainer/build-images.sh --run
ls -lh runtime/apptainer/*.sif | tee ".agent-runs/creator-build-sif/${SLURM_JOB_ID}.images.txt"

printf 'finished=%s\n' "$(date -Iseconds)" | tee -a ".agent-runs/creator-build-sif/${SLURM_JOB_ID}.env"
