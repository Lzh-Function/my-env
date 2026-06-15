---
name: git-worktree
description:
  Guide for using git worktrees. Use this when creating branches, switching
  between parallel workstreams, or when the agentrun hook auto-creates a worktree.
---

# git worktree

A git worktree lets you check out multiple branches simultaneously in separate
directories, without cloning the repository again. Each worktree shares the same
`.git` object store.

## How agentrun uses worktrees

agentrun includes a `git_worktree_auto_create.py` PostToolUse hook. When you run
`git checkout -b <branch>` or `git switch -c <branch>`, the hook automatically
creates a worktree for that branch at `../<branch>` relative to the current
working directory.

Inside the capsule, the main repository is at `/workspace`. A new branch
`feature/foo` will result in a worktree at `/workspace/../feature/foo`. Note that
sibling directories of `/workspace` are not bound into the container by default,
so newly auto-created worktrees may not be accessible within the same run. Create
branches and use them within `/workspace` unless you have a specific reason to
work in a separate worktree.

## Basic commands

```bash
# List all worktrees
git worktree list

# Add a worktree for an existing branch
git worktree add ../other-branch other-branch

# Add a worktree and create the branch at the same time
git worktree add -b new-feature ../new-feature main

# Remove a worktree (after work is done)
git worktree remove ../new-feature

# Prune stale worktree metadata
git worktree prune
```

## Typical workflow

```bash
# 1. Create a branch and worktree together
git worktree add -b experiment/run-42 ../experiment-run-42 main

# 2. Work inside /workspace on the main branch, or move to the worktree
cd ../experiment-run-42
# ... make changes ...
git add -p
git commit -m "experiment: run 42 results"

# 3. Return to main workspace
cd /workspace

# 4. Clean up when done
git worktree remove ../experiment-run-42
```

## Rules in this capsule

- Do not checkout or switch to `main` or `master` directly — the
  `git_branch_guard.py` hook blocks this.
- Do not run `git merge` or `git rebase` — also blocked.
- Always create a new branch before making changes to keep the diff clean for
  `artifacts/git_diff.patch`.
