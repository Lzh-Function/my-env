---
name: slurm
description:
  Guide for understanding the SLURM environment from inside an agentrun capsule.
  Use this when you need to know what SLURM commands are available, what is
  restricted, and how to inspect job or cluster state.
---

# SLURM inside an agentrun capsule

You are running inside a SLURM job. The job was submitted by `agentrun` and you
are inside an Apptainer container on a compute node.

## Environment variables

```bash
$SLURM_JOB_ID          your job ID
$SLURMD_NODENAME       the compute node you are running on
$SLURM_CPUS_PER_TASK   CPU cores allocated to this job
$SLURM_MEM_PER_NODE    memory allocated (MB)
$SLURM_GPUS            number of GPUs (if requested)
```

## What you can do

Read-only inspection of the cluster is allowed:

```bash
squeue -u $USER                  # list your jobs
squeue -j $SLURM_JOB_ID         # status of this job
sinfo                            # partition and node status
scontrol show job $SLURM_JOB_ID # detailed job info
```

## What is blocked

The `check_sbatch_forbidden.py` hook blocks job submission from inside a running
allocation. These commands will be denied:

```bash
sbatch ...    # BLOCKED — cannot submit nested jobs
salloc ...    # BLOCKED — cannot allocate nested interactive sessions
```

This is enforced because nested SLURM allocations consume cluster resources
unexpectedly and can deadlock.

## What to do instead of sbatch

If your task requires running a subprocess as a compute job, write it to
`/runs/artifacts/proposed_train.sbatch` and document it in your report. The
operator will submit it after reviewing your output.

For campaign mode, `artifacts/proposed_train.sbatch` is a required output — write
a ready-to-submit sbatch script there.

## Python on compute nodes

There is no system Python. Use `uv` (see the `uv` skill). The uv binary is
available at `/usr/local/bin/uv` inside the container.

```bash
uv run python script.py
uv run pytest tests/
```

Do not call `python` or `python3` directly — it may not exist.

## GPU access

If the job was submitted with `--gpus 1`, the GPU is visible via:

```bash
nvidia-smi              # show GPU status
echo $CUDA_VISIBLE_DEVICES
```

The container is launched with `--nv` when GPUs are allocated, which passes
NVIDIA drivers through from the host.

## Resource limits

Do not exceed the resources allocated to this job. Exceeding memory causes the
job to be killed by SLURM (OOM). Check your allocation:

```bash
scontrol show job $SLURM_JOB_ID | grep -E "MinMemory|NumCPUs|GRES"
```
