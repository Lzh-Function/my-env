#!/usr/bin/env bash
# PostToolUse hook: after branch creation, also create a worktree at ../<branch>

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

[ -z "$cmd" ] && exit 0

branch_name=""

# git checkout -b <branch> [base]
if echo "$cmd" | grep -qE 'git\s+checkout\s+(-b|-B)\s+'; then
    branch_name=$(echo "$cmd" | grep -oP '(?<=-b\s|(?<=-B\s))\S+' | head -1)
    # fallback for cases where -oP isn't available
    if [ -z "$branch_name" ]; then
        branch_name=$(echo "$cmd" | sed -E 's/.*git\s+checkout\s+(-b|-B)\s+(\S+).*/\2/')
    fi
# git switch -c / --create <branch> [base]
elif echo "$cmd" | grep -qE 'git\s+switch\s+(-c|--create)\s+'; then
    branch_name=$(echo "$cmd" | sed -E 's/.*git\s+switch\s+(-c|--create)\s+(\S+).*/\2/')
fi

[ -z "$branch_name" ] && exit 0

# Strip trailing semicolons or other shell operators that may have been captured
branch_name=$(echo "$branch_name" | tr -d ';|&')

repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
[ -z "$repo_root" ] && exit 0

worktree_path="$(dirname "$repo_root")/$branch_name"

# Skip if worktree already exists
if git -C "$repo_root" worktree list 2>/dev/null | grep -qF "$worktree_path"; then
    exit 0
fi

# Skip if directory already exists (safety guard)
if [ -e "$worktree_path" ]; then
    echo "警告: $worktree_path は既に存在するためworktreeの作成をスキップしました。" >&2
    exit 0
fi

git -C "$repo_root" worktree add "$worktree_path" "$branch_name" 2>&1
echo "worktree を作成しました: $worktree_path"

exit 0
