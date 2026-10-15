---
name: experiment-report
description:
  Formats and conventions for experiment, campaign, review, and multi-review
  output files. Use this when writing proposed_next.yaml, proposed_train.sbatch,
  review_findings.json, or any mode-specific artifact.
---

# experiment and review output formats

This skill covers mode-specific output files beyond the base contract. See the
`agentrun-contract` skill for the full list of required files per mode.

## experiment mode

### `artifacts/proposed_next.yaml`

Propose the next action for the operator to take. Follow the same schema as
`goal.yaml`:

```yaml
project: my-project
mode: experiment        # or campaign, review, etc.
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

## review mode

### `reviews/review_findings.json`

Structured review findings. Use this schema:

```json
{
  "summary": "One-sentence overall assessment.",
  "verdict": "approve | request_changes | comment",
  "findings": [
    {
      "severity": "critical | major | minor | nit",
      "file": "path/to/file.py",
      "line": 42,
      "message": "Description of the issue.",
      "suggestion": "How to fix it (optional)."
    }
  ],
  "praise": [
    "What was done well."
  ]
}
```

`verdict` values:
- `approve` — no blocking issues
- `request_changes` — blocking issues must be resolved before merge
- `comment` — non-blocking observations only

## multi-review mode

### `reviews/<agent>.md` (claude.md, codex.md, antigravity.md)

Each agent writes its own review as a markdown document:

```markdown
# Review by <Agent>

## Overall Assessment
approve / request_changes / comment

## Critical Issues
- ...

## Minor Issues
- ...

## Positive Observations
- ...
```

### `reviews/disagreements.json`

Document where agents disagreed:

```json
{
  "disagreements": [
    {
      "file": "src/model.py",
      "line": 88,
      "topic": "Whether to use dropout here.",
      "positions": {
        "claude": "Dropout is not needed; the model is already regularized.",
        "codex": "Dropout at 0.1 would help generalization.",
        "antigravity": "Agreed with codex."
      }
    }
  ]
}
```

### `reviews/final_recommendation.md`

Synthesis of all agent reviews:

```markdown
# Final Recommendation

**Verdict:** approve | request_changes | comment

## Consensus Findings
Issues all agents agreed on.

## Resolved Disagreements
How disagreements were resolved.

## Action Items
- [ ] Fix X before merge.
- [ ] Consider Y in a follow-up.
```

### `reviews/summary.md`

One-page summary for the operator:

```markdown
# Review Summary

Reviewed: <description of what was reviewed>
Agents: claude, codex, antigravity
Verdict: approve / request_changes / comment

## Key Findings
- ...
```
