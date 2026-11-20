#!/usr/bin/env bash
# Install the agent-history command for this user (uv tool, editable: edits here take effect).
#   ./install.sh            install or update
#   ./install.sh --remove   uninstall the command (hooks: run `agent-history hooks uninstall` first)
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
command -v uv >/dev/null 2>&1 || { printf 'uv が見つかりません: https://docs.astral.sh/uv/ を参照して導入してください\n' >&2; exit 1; }
if [ "${1:-}" = --remove ]; then
    uv tool uninstall agent-history
    exit 0
fi
uv tool install --force --editable "$here"
printf '\nインストールしました。次は:\n  agent-history sync            # 今ある会話を保存\n  agent-history hooks install   # 返答ごとの自動保存を登録\n'
