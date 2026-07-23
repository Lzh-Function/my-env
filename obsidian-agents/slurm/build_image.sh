#!/usr/bin/env bash
# =============================================================================
#  ログインノードから実行する: 計算ノード上でApptainerイメージをビルドする。
#
#  ビルド自体もベースイメージの取得・パッケージインストールでそれなりに負荷が
#  かかるため、ログインノードでは行わず計算ノード側で行う(GPU割り当ては不要)。
#
#  使い方:
#     bash build_image.sh
#
#  ★ 要調整(クラスタごとに違うので後で書き換えること):
#     - SRUN_OPTS のパーティション名・時間制限(CPUのみでよく、GPU不要)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIF_IMAGE="$HOME/obsidian-agents/agent.sif"

mkdir -p "$HOME/obsidian-agents"

# --- TODO: クラスタに合わせて書き換える(GPU不要、CPU/ビルド用パーティションでよい) ---
SRUN_OPTS=(
    --partition=CHANGE_ME
    --time=00:30:00
    --pty
)
# -----------------------------------------------------------------------------

# unprivilegedユーザーは既定でfakerootが自動的に使われる。クラスタ側でuser namespace
# が制限されていて失敗する場合は、以下に `--fakeroot` を明示するか管理者に確認する。
srun "${SRUN_OPTS[@]}" apptainer build "$SIF_IMAGE" "$SCRIPT_DIR/agent.def"
