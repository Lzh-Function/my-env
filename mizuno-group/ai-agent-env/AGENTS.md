# ai-agent-env Test Instructions

These instructions apply to test jobs for this directory.

## Creator Partitions

Creator test jobs must be submitted from a current working directory under `/workspace/filesrv01`.

Use creator partitions only for tests, not in product runtime scripts:

- `small-creator`: up to 1 hour
- `medium-creator`: up to 2 hours
- `large-creator`: up to 4 hours
- `x-large-creator`: longer than 4 hours; always specify both `--time` and `--mem`

Creator nodes have one GPU per node. Keep memory at or below `120000M`.

## Test Scope

- Build SIF files through Slurm, not on the login node.
- Run agent CLI smoke tests through Slurm and Apptainer, not on the login node.
- Keep test logs and run directories under `.agent-runs/`.
