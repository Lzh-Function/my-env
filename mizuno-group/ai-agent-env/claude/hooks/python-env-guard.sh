#!/usr/bin/env bash
# PreToolUse hook: ensure correct venv is activated in SLURM Python jobs.
# Handles both srun (inline) and sbatch (job script) patterns.

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
[ -z "$cmd" ] && exit 0

# Only trigger for srun/sbatch
echo "$cmd" | grep -qE '^\s*(srun|sbatch)\b' || exit 0

block() {
    printf '{"decision":"block","reason":"%s"}\n' "$1"
    exit 2
}

session_env_file="/tmp/claude_python_env_$(pwd | md5sum | cut -c1-8)"
selected_env=""
[ -f "$session_env_file" ] && selected_env=$(cat "$session_env_file" | tr -d '[:space:]')

# Validate selected env if set
if [ -n "$selected_env" ] && [ ! -f "${selected_env}/bin/activate" ]; then
    selected_env=""
fi

list_envs() {
    find . -maxdepth 5 -name "activate" -path "*/bin/activate" 2>/dev/null \
        | sed 's|/bin/activate||' | sort | tr '\n' '  /  '
}

# ── srun: inline command ──────────────────────────────────────────
if echo "$cmd" | grep -qE '^\s*srun\b'; then
    echo "$cmd" | grep -qE '\bpython[0-9.]*\b' || exit 0

    if ! echo "$cmd" | grep -q 'source.*activate'; then
        if [ -n "$selected_env" ]; then
            block "srunコマンドにsource activateがありません。以下の形式で再試行してください: srun <options> bash -c \"source ${selected_env}/bin/activate && python ...\""
        else
            block "srunコマンドにsource activateがなく、使用するvenvが未設定です。利用可能なenv: $(list_envs)。ユーザーにどのenvを使うか確認し、\`echo '<パス>' > ${session_env_file}\` を実行してから再試行してください。"
        fi
    fi
fi

# ── sbatch: job script ───────────────────────────────────────────
if echo "$cmd" | grep -qE '^\s*sbatch\b'; then
    script_path=$(echo "$cmd" | grep -oE '[^[:space:]]+\.sh' | tail -1)
    [ -z "$script_path" ] && exit 0
    [ -f "$script_path" ] || exit 0
    grep -q 'python' "$script_path" || exit 0

    if ! grep -q 'source.*activate' "$script_path"; then
        if [ -n "$selected_env" ]; then
            block "ジョブスクリプト(${script_path})にsource activateがありません。python呼び出しの前に \`source ${selected_env}/bin/activate\` を追記してください。"
        else
            block "ジョブスクリプト(${script_path})にsource activateがなく、使用するvenvが未設定です。利用可能なenv: $(list_envs)。ユーザーにどのenvを使うか確認し、\`echo '<パス>' > ${session_env_file}\` を実行してからスクリプトに追記して再試行してください。"
        fi
    fi
fi

exit 0
