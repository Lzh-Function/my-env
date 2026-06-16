## SLURM environment: creator[1-7]

For this project (**ONLY AT TEST**), you can test scripts to creator[1-7] node partitions as below.
REMEMBER: **DONT WRITE SPECIFIC PARTITION NAME IN THE PRODUCT SCRIPT**, just use these partition in test.

Available partitions:

| Partition         |     Time limit | Notes                                                                            |
| ----------------- | -------------: | -------------------------------------------------------------------------------- |
| `small-creator`   |         1 hour |                                                                                  |
| `medium-creator`  |        2 hours |                                                                                  |
| `large-creator`   |        4 hours |                                                                                  |
| `x-large-creator` | No upper limit | Only for jobs longer than 4 hours. Time and memory must be explicitly specified. |

Resource constraints:

- Memory limit: `120000MB`
- GPUs: `1` for each node, 7 nodes in total.

When using `srun` or `sbatch`, select the partition according to the expected runtime and respect the corresponding time limit. For `x-large-creator`, always specify both `--time` and `--mem`.

When using `python`, activating the environments under `00_env/python/` is required. For example, `source 00_env/python/mini_env/.venv/bin/activate` to activate the `mini_env` environment.