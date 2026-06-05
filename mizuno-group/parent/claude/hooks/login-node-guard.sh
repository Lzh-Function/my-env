#!/usr/bin/env bash
# PreToolUse hook: block direct compute execution on SLURM login node.
# Any Python/Jupyter/training command must go through srun or sbatch.

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

[ -z "$cmd" ] && exit 0

# Already wrapped in srun/sbatch — allow
if echo "$cmd" | grep -qE '^\s*(srun|sbatch)\b'; then
    exit 0
fi

block() {
    printf '{"decision":"block","reason":"%s"}\n' "$1"
    exit 2
}

# Detect compute commands that must not run directly on the login node.
# Pattern: command appears at start of cmd, after pipe/semicolon/&&/||, or after env assignments.
is_compute_cmd() {
    local cmd="$1"
    # Strip leading env var assignments (e.g. CUDA_VISIBLE_DEVICES=0 python ...)
    local stripped
    stripped=$(echo "$cmd" | sed 's/^[A-Z_][A-Z_0-9]*=[^ ]* //g')

    echo "$stripped" | grep -qE \
        '(^|[|;&\s])\s*(python[0-9.]*|python3\.[0-9]+|ipython|jupyter\s*(notebook|lab|console|nbconvert|execute)?|pytest|torchrun|deepspeed|accelerate\s+launch|lightning\s+run|vina|gnina|smina|autodock|xtb|crest|mmpbsa\.py)\b'
}

if is_compute_cmd "$cmd"; then
    # Allow pure introspection that has no compute cost
    if echo "$cmd" | grep -qE '\s*(-V|--version|--help|-h)\s*$'; then
        exit 0
    fi
    block "ログインノードでの直接実行は禁止です: ${cmd%% *} はsrunまたはsbatchで投入してください。パーティション等の引数はプロジェクトの./CLAUDE.mdを確認してください。"
fi

exit 0
