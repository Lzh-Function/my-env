#!/usr/bin/env bash
# Blocks dangerous git operations to prevent working directly on main/master,
# and prevents git merge / git rebase.

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)

[ -z "$cmd" ] && exit 0

block() {
    printf '{"decision":"block","reason":"%s"}\n' "$1"
    exit 2
}

# Block: git checkout/switch to main or master (exact branch name, not prefix like main-feature)
if echo "$cmd" | grep -qE 'git\s+(checkout|switch)\s+(main|master)(\s|$)'; then
    block "mainブランチへの直接チェックアウトは禁止されています。新しいブランチを作成して作業してください。"
fi

# Block: git merge (allow --abort/--continue/--quit to recover from conflicts)
if echo "$cmd" | grep -qE 'git\s+merge\b' && \
   ! echo "$cmd" | grep -qE 'git\s+merge\s+--(abort|continue|quit)\b'; then
    block "git merge は禁止されています。ユーザーに委ねてください。"
fi

# Block: git rebase (allow --abort/--continue/--quit/--skip to recover)
if echo "$cmd" | grep -qE 'git\s+rebase\b' && \
   ! echo "$cmd" | grep -qE 'git\s+rebase\s+--(abort|continue|quit|skip)\b'; then
    block "git rebase は禁止されています。ユーザーに委ねてください。"
fi

# Block: direct .git directory access (e.g. cat .git/config, rm -rf .git)
# Matches ".git" preceded by start/space/slash and followed by slash/space/end.
# Does NOT match --git-dir=.git style flags (= is not a valid preceding char).
if echo "$cmd" | grep -qE '(^|\s|/)\.git(/|\s|$)'; then
    block ".git ディレクトリへの直接操作は禁止されています。"
fi

exit 0