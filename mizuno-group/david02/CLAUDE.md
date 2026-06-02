## SLURM environment: david02

This working directory is located on the `david02` SLURM cluster node. Use `srun` or `sbatch` for GPU workloads and non-trivial code execution; do not run such workloads directly on the login node except for trivial sanity checks.

Available partitions:

| Partition         |     Time limit | Notes                                                                            |
| ----------------- | -------------: | -------------------------------------------------------------------------------- |
| `small-david02`   |         1 hour |                                                                                  |
| `medium-david02`  |        2 hours |                                                                                  |
| `large-david02`   |        4 hours |                                                                                  |
| `x-large-david02` | No upper limit | Only for jobs longer than 4 hours. Time and memory must be explicitly specified. |

Resource constraints:

- Memory limit: `120000MB`
- GPUs: `1`

Because only one GPU is available, GPU jobs cannot be executed in parallel when another GPU job is already running.

When using `srun` or `sbatch`, select the partition according to the expected runtime and respect the corresponding time limit. For `x-large-david02`, always specify both `--time` and `--mem`.