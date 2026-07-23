#!/usr/bin/env bash
# =============================================================================
#  ログインノードから実行する: 計算ノード上のApptainerコンテナでエージェントを起動する。
#
#  ログインノード側の認証情報(~/.claude, ~/.claude.json, ~/.codex, ~/.ssh)と
#  obsidian-vaultのclone、実験の作業ディレクトリをそれぞれbind mountするので、
#  計算ノード側では追加のログインやclone操作なしでそのまま使える。
#
#  使い方:
#     bash run_agent_node.sh <実験の作業ディレクトリ>
#
#  ★ 要調整(クラスタごとに違うので後で書き換えること):
#     - SRUN_OPTS のパーティション名・GPU要求・時間制限
#     - SIF_IMAGE のパス(事前に `apptainer build agent.sif agent.def` で作成)
# =============================================================================
set -euo pipefail

WORKDIR="${1:?使い方: run_agent_node.sh <作業ディレクトリ>}"
WORKDIR="$(realpath "$WORKDIR")"

VAULT_DIR="$HOME/obsidian-vault"
SIF_IMAGE="$HOME/obsidian-agents/agent.sif"

[ -d "$VAULT_DIR" ] || { echo "[error] $VAULT_DIR が見つかりません。先に setup_login_node.sh を実行してください" >&2; exit 1; }
[ -f "$SIF_IMAGE" ] || { echo "[error] $SIF_IMAGE が見つかりません。先に 'apptainer build $SIF_IMAGE agent.def' を実行してください" >&2; exit 1; }

# --- TODO: クラスタに合わせて書き換える -------------------------------------
SRUN_OPTS=(
    --partition=CHANGE_ME
    --gres=gpu:1
    --time=02:00:00
    --pty
)
# -----------------------------------------------------------------------------

# obsidian-skills は $VAULT_DIR/.claude/skills/ にプロジェクトスコープで入っている
# (setup_login_node.sh参照)ため、エージェントはVaultディレクトリ内で起動する。
# 実験の作業ディレクトリは EXPERIMENT_WORKDIR として渡すので、そこを見るよう
# エージェントに指示する形になる(bind mountはしてあるのでパスはそのまま読める)。
echo "実験の作業ディレクトリ: $WORKDIR (エージェントにこのパスを伝えて参照させてください)"

exec srun "${SRUN_OPTS[@]}" apptainer exec --nv \
    --bind "$HOME/.claude:$HOME/.claude" \
    --bind "$HOME/.claude.json:$HOME/.claude.json" \
    --bind "$HOME/.codex:$HOME/.codex" \
    --bind "$HOME/.ssh:$HOME/.ssh:ro" \
    --bind "$VAULT_DIR:$VAULT_DIR" \
    --bind "$WORKDIR:$WORKDIR" \
    --env "EXPERIMENT_WORKDIR=$WORKDIR" \
    "$SIF_IMAGE" \
    bash -lc "cd '$VAULT_DIR' && exec bash -l"
