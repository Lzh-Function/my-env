#!/usr/bin/env bash
# =============================================================================
#  ログインノード側セットアップ(Slurmクラスタ)
#
#  ここではClaude Code / Codexを「ログインするためだけ」に導入する。実際の
#  エージェント駆動作業はこのノードでは行わない(ノード負荷の都合上非推奨)。
#  ログイン情報(~/.claude, ~/.claude.json, ~/.codex)は計算ノード側の
#  Apptainerコンテナへ run_agent_node.sh が bind mount で渡す。
#
#  使い方:
#     bash setup_login_node.sh
# =============================================================================
set -euo pipefail

VAULT_REPO='git@github.com:Lzh-Function/obsidian-vault.git'
VAULT_DIR="$HOME/obsidian-vault"

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }

log "Claude Code をインストール(ログイン専用。ここでは実行しないこと)"
if ! command -v claude >/dev/null 2>&1; then
    curl -fsSL https://claude.ai/install.sh | bash
fi

log "Codex CLI をインストール(ログイン専用)"
if ! command -v codex >/dev/null 2>&1; then
    if ! command -v npm >/dev/null 2>&1; then
        warn "npm が見つかりません。クラスタのmoduleシステム等でNode.jsを導入してから再実行してください"
        warn "(例: module load nodejs 、または管理者にnodejs/npmの導入を依頼)"
    else
        npm install -g @openai/codex
    fi
fi

log "obsidian-vault を clone: $VAULT_REPO -> $VAULT_DIR"
if [ ! -d "$VAULT_DIR" ]; then
    git clone "$VAULT_REPO" "$VAULT_DIR"
else
    warn "$VAULT_DIR は既に存在するので clone をスキップ"
fi

log "obsidian-skills を導入(Claude Code / Codex 両方を自動検出)"
# Windows側(setup_obsidian.ps1)と同じ仕組み。Vaultディレクトリ内で実行することで
# Claude Codeは $VAULT_DIR/.claude/skills/ にプロジェクトスコープでインストールされる
# (計算ノード側でも $VAULT_DIR ごとbind mountするので、コンテナ内でもそのまま使える)。
if command -v npx >/dev/null 2>&1; then
    ( cd "$VAULT_DIR" && npx skills add https://github.com/kepano/obsidian-skills --all -y )
else
    warn "npx(Node.js)が見つからないため obsidian-skills の導入をスキップしました"
    warn "Node.js導入後に再実行するか、手動で: cd $VAULT_DIR && npx skills add https://github.com/kepano/obsidian-skills --all -y"
fi

cat <<'DONE'

  次に、ログイン情報を作るために一度だけ手動でログインしてください
  (このログインノード上で、対話的に。ブラウザでのOAuth認証が必要):

      claude
      codex

  ログインが終わったら、実際の作業は計算ノードで行います:

      bash run_agent_node.sh <実験の作業ディレクトリ>

  ★ 重要: このログインノードで claude / codex を使った重い作業(実際のagent
    ループなど)は行わないこと。ここで作った ~/.claude・~/.claude.json・~/.codex
    は計算ノード側のコンテナへそのままマウントして再利用するためのものです。

DONE
