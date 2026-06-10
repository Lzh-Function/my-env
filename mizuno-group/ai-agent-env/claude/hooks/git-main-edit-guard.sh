#!/usr/bin/env bash
# PreToolUse hook for Edit/Write/NotebookEdit:
# When the target file is in a git repo on main/master, ask user for confirmation.
# Once user confirms, bypass is stored in /tmp/claude_allow_main_edit for the session.

input=$(cat)

# Session-level bypass: user already confirmed
[ -f /tmp/claude_allow_main_edit ] && exit 0

file_path=$(echo "$input" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
[ -z "$file_path" ] && exit 0

dir=$(dirname "$file_path")
current_branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)

# Not a git repo, or detached HEAD — allow
[ -z "$current_branch" ] || [ "$current_branch" = "HEAD" ] && exit 0

if [ "$current_branch" = "main" ] || [ "$current_branch" = "master" ]; then
    printf '{"decision":"block","reason":"%s"}\n' \
        "編集対象ファイル (${file_path}) は ${current_branch} ブランチにあります。ユーザーに確認し、指示に従ってください: (1) mainに直接編集してよい → あなたが \`touch /tmp/claude_allow_main_edit\` を実行してから編集を再試行 / (2) 新しいブランチを切ってほしい → ブランチ名を聞いてブランチ作成後に編集 / (3) 中止"
    exit 2
fi

exit 0
