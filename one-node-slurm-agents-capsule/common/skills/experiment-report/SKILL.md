---
name: experiment-report
description:
  Formats and conventions for experiment and campaign output files. Use this
  when writing proposed_next.yaml, proposed_train.sbatch, or any mode-specific
  artifact.
---

# experiment and campaign output formats

This skill covers mode-specific output files beyond the base contract. See the
`agentrun-contract` skill for the full list of required files per mode.

## experiment mode

### `artifacts/proposed_next.yaml`

Propose the next action for the operator to take. Follow the same schema as
`goal.yaml`:

```yaml
project: my-project
mode: experiment        # or campaign
goal:
  objective: |
    What should happen next, based on findings from this run.
  success_criteria:
    - specific measurable outcome
budgets:
  walltime: "01:00:00"
  cpu_cores: 2
  memory: 8G
  max_trials: 1
  max_disk_gb: 10
outputs:
  required:
    - artifacts/report.md
    - artifacts/metrics.json
```

## campaign mode

### `artifacts/proposed_next.yaml`

Same schema as experiment. Describe the next campaign step.

### `artifacts/proposed_train.sbatch`

A ready-to-submit sbatch script for the training job the campaign recommends.
The operator will review and submit it. Write a complete, working script:

```bash
#!/usr/bin/env bash
#SBATCH --job-name=train-my-model
#SBATCH --partition=<partition>
#SBATCH --time=04:00:00
#SBATCH --mem=32G
#SBATCH --cpus-per-task=4
#SBATCH --gres=gpu:1
#SBATCH --output=/path/to/logs/slurm.out
#SBATCH --error=/path/to/logs/slurm.err

set -euo pipefail
source /path/to/.venv/bin/activate
python train.py --config config.yaml
```

