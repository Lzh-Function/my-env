#!/usr/bin/env bash
# =============================================================================
#  WezTerm + Zellij + Docker(uv) 開発環境 セットアップスクリプト(WSL/Ubuntu)
#
#  クリーンな WSL(Ubuntu)から、作業ディレクトリ作成 → docker build →
#  `zj py` が使える状態までを一気通貫で構築する。
#
#  ● 非対話: 最初の sudo パスワード入力のみ(apt に必要)。それ以外は無人。
#  ● 冪等性: 再実行しても壊れないよう、存在チェック/バックアップを行う。
#
#  使い方:
#     bash setup-wsl-dev.sh              # Python 環境をビルドして zj py まで
#     bash setup-wsl-dev.sh --with-latex # LaTeX(texlive)コンテナもビルド(巨大・時間大)
#
#  前提(Windows 側で先に済ませておくこと。このスクリプトでは扱えない):
#     - WezTerm 本体 + Nerd Font のインストール
#     - LaTeX を使うなら SumatraPDF
# =============================================================================
set -euo pipefail

WITH_LATEX=0
[[ "${1:-}" == "--with-latex" ]] && WITH_LATEX=1

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

WORKSPACE="$HOME/workspace"
PYDIR="$WORKSPACE/Python-Work"
TEXDIR="$WORKSPACE/LaTeX-Work"

# --- 0. 事前チェック --------------------------------------------------------
log "事前チェック"
command -v sudo >/dev/null || die "sudo が見つかりません。"
sudo -v || die "sudo 認証に失敗しました。"
# sudo タイムアウト対策:バックグラウンドで認証を維持
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
SUDO_KEEPALIVE_PID=$!
trap 'kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true' EXIT

# --- 1. apt パッケージ ------------------------------------------------------
log "apt パッケージのインストール"
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    btop git curl ca-certificates build-essential \
    ripgrep fd-find nodejs npm unzip
# Ubuntu では fd は fdfind。fd という名前でも使えるようリンク
mkdir -p "$HOME/.local/bin"
[[ -e "$HOME/.local/bin/fd" ]] || ln -s "$(command -v fdfind)" "$HOME/.local/bin/fd" 2>/dev/null || true

# --- 2. Rust(rustup)+ cargo -----------------------------------------------
if ! command -v cargo >/dev/null 2>&1; then
    log "Rust(rustup)を非対話インストール"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
# 現在のシェルへ反映(以降 cargo/zellij を使うため)
[[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# --- 3. Zellij(cargo)------------------------------------------------------
if ! command -v zellij >/dev/null 2>&1; then
    log "Zellij を cargo でインストール(コンパイルに数分かかります)"
    cargo install zellij --locked
fi

# --- 4. Neovim(tarball で新しめを導入)------------------------------------
if ! command -v nvim >/dev/null 2>&1; then
    log "Neovim をインストール"
    tmp="$(mktemp -d)"
    curl -Lo "$tmp/nvim.tar.gz" \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
    sudo tar xzf "$tmp/nvim.tar.gz" -C /opt
    sudo ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim
    rm -rf "$tmp"
fi

# --- 5. LazyVim(スターター + extras + キーマップ)-------------------------
log "LazyVim を導入"
if [[ ! -d "$HOME/.config/nvim" ]]; then
    git clone --depth 1 https://github.com/LazyVim/starter "$HOME/.config/nvim"
    rm -rf "$HOME/.config/nvim/.git"
else
    warn "~/.config/nvim が既に存在。設定はそのまま使います(上書きしません)。"
fi

# lang.python / lang.tex を :LazyExtras を使わず lazyvim.json で有効化(非対話)
cat > "$HOME/.config/nvim/lazyvim.json" <<'JSON'
{
  "extras": [
    "lazyvim.plugins.extras.lang.python",
    "lazyvim.plugins.extras.lang.tex"
  ],
  "install_version": 8,
  "news": {},
  "version": 8
}
JSON

# キーマップ:Ctrl+Z 無効化 + SumatraPDF プレビュー(<leader>v)
mkdir -p "$HOME/.config/nvim/lua/config"
KM="$HOME/.config/nvim/lua/config/keymaps.lua"
touch "$KM"
if ! grep -q 'setup-wsl-dev:keymaps' "$KM" 2>/dev/null; then
cat >> "$KM" <<'LUA'

-- setup-wsl-dev:keymaps ------------------------------------------------------
-- Ctrl+Z(VS Code 癖のサスペンド暴発)を無効化。取り消しは u / やり直しは <C-r>
vim.keymap.set({ "n", "i", "v" }, "<C-z>", "<Nop>")

-- <leader>v : 現在の .tex に対応する PDF を Windows の SumatraPDF で開く
vim.keymap.set("n", "<leader>v", function()
  local pdf = vim.fn.expand("%:p:r") .. ".pdf"
  vim.fn.jobstart({ vim.fn.expand("$HOME/.local/bin/pdfview"), pdf })
end, { desc = "View PDF (SumatraPDF)" })
-- ---------------------------------------------------------------------------
LUA
fi

# プラグインを headless で同期(LSP/treesitter は初回 zj py 起動時に自動完了)
log "Neovim プラグインを同期(headless)"
nvim --headless "+Lazy! sync" +qa 2>/dev/null || warn "Lazy sync で警告が出ましたが続行します。"

# --- 6. Zellij 設定 & レイアウト -------------------------------------------
log "Zellij 設定とレイアウトを配置"
mkdir -p "$HOME/.config/zellij/layouts"

cat > "$HOME/.config/zellij/config.kdl" <<'KDL'
theme "catppuccin-mocha"
pane_frames false
copy_command "clip.exe"          // WSL → Windows クリップボード
session_serialization false      // 前回のペイン状態を復元しない(復元事故の防止)
KDL

cat > "$HOME/.config/zellij/layouts/py.kdl" <<'KDL'
layout {
    default_tab_template {
        children
        pane size=1 borderless=true {
            plugin location="zellij:compact-bar"
        }
    }
    tab name="work" {
        pane split_direction="vertical" {
            pane size="65%" name="editor" {
                command "bash"
                args "-c" "nvim"
            }
            pane name="container" {
                command "bash"
                args "-c" "docker compose up -d && docker compose exec app bash"
            }
        }
    }
    tab name="monitor" {
        pane name="btop" {
            command "btop"
        }
    }
}
KDL

cat > "$HOME/.config/zellij/layouts/tex.kdl" <<'KDL'
layout {
    default_tab_template {
        children
        pane size=1 borderless=true {
            plugin location="zellij:compact-bar"
        }
    }
    tab name="work" {
        pane split_direction="vertical" {
            pane size="65%" name="editor" {
                command "bash"
                args "-c" "nvim"
            }
            pane name="container" {
                command "bash"
                args "-c" "docker compose up -d && docker compose exec tex bash"
            }
        }
    }
    tab name="monitor" {
        pane name="btop" {
            command "btop"
        }
    }
}
KDL

# --- 7. pdfview ラッパー(SumatraPDF)-------------------------------------
# Windows ユーザー名を best-effort で検出(取れなければ TAKUH を仮置き)
WINUSER="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r' || true)"
[[ -z "$WINUSER" ]] && WINUSER="TAKUH"
cat > "$HOME/.local/bin/pdfview" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SUMATRA="/mnt/c/Users/${WINUSER}/AppData/Local/SumatraPDF/SumatraPDF.exe"
pdf_win="\$(wslpath -w "\$(realpath "\$1")")"
"\$SUMATRA" -reuse-instance "\$pdf_win" >/dev/null 2>&1 &
disown
EOF
chmod +x "$HOME/.local/bin/pdfview"

# --- 8. .bashrc(PATH と zj 関数)------------------------------------------
log ".bashrc に PATH と zj 関数を追記"
BRC="$HOME/.bashrc"
if ! grep -q 'setup-wsl-dev:bashrc' "$BRC" 2>/dev/null; then
cat >> "$BRC" <<'BASH'

# setup-wsl-dev:bashrc -------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"

# zellij work env
zj() {
  case "$1" in
    py)  cd ~/workspace/Python-Work && zellij --layout py  attach --create "py-$(date +%s)"  ;;
    tex) cd ~/workspace/LaTeX-Work  && zellij --layout tex attach --create "tex-$(date +%s)" ;;
    *)   zellij "$@" ;;
  esac
}
zjdel() {
  zellij kill-all-sessions
}
# ---------------------------------------------------------------------------
BASH
fi

# --- 9. 作業ディレクトリとプロジェクトファイル -----------------------------
log "作業ディレクトリを作成"
mkdir -p "$PYDIR" "$TEXDIR"

# Python-Work
cat > "$PYDIR/Dockerfile" <<'DOCKER'
# syntax=docker/dockerfile:1
FROM python:3.13.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace/Python-Work
CMD ["sleep", "infinity"]
DOCKER

cat > "$PYDIR/compose.yml" <<'YAML'
services:
  app:
    build:
      context: .
    working_dir: /workspace/Python-Work
    volumes:
      - ${HOME}/workspace/Python-Work:/workspace/Python-Work
    tty: true
    stdin_open: true
YAML

cat > "$PYDIR/.dockerignore" <<'IGN'
.venv
.git
__pycache__
*.pyc
IGN

# LaTeX-Work
cat > "$TEXDIR/Dockerfile" <<'DOCKER'
FROM texlive/texlive:latest
WORKDIR /workspace/LaTeX-Work
CMD ["sleep", "infinity"]
DOCKER

cat > "$TEXDIR/compose.yml" <<'YAML'
services:
  tex:
    build:
      context: .
    working_dir: /workspace/LaTeX-Work
    volumes:
      - ${HOME}/workspace/LaTeX-Work:/workspace/LaTeX-Work
    tty: true
    stdin_open: true
YAML

cat > "$TEXDIR/.latexmkrc" <<'PERL'
$pdf_mode = 4;                 # 4 = lualatex
$lualatex = 'lualatex %O %S';
PERL

# --- 10. Docker ビルド + uv 初期化 -----------------------------------------
command -v docker >/dev/null 2>&1 || die "docker が見つかりません。Docker Desktop の WSL Integration を ON にしてから再実行してください。"
docker compose version >/dev/null 2>&1 || die "'docker compose' が使えません。Docker Desktop を確認してください。"

log "Python コンテナをビルド"
( cd "$PYDIR" && docker compose build && docker compose up -d )

log "コンテナ内で uv プロジェクトを初期化(.venv 生成)"
( cd "$PYDIR" && docker compose exec -T app bash -lc '
    cd /workspace/Python-Work
    [ -f pyproject.toml ] || uv init --bare 2>/dev/null || uv init --name python-work
    uv add numpy pandas polars scikit-learn matplotlib seaborn
' ) || warn "uv 初期化で警告。あとで手動: docker compose exec app uv add numpy pandas polars scikit-learn matplotlib seaborn"

if [[ "$WITH_LATEX" -eq 1 ]]; then
    log "LaTeX(texlive)コンテナをビルド(巨大・時間がかかります)"
    ( cd "$TEXDIR" && docker compose build && docker compose up -d )
else
    warn "LaTeX コンテナは未ビルド(--with-latex で有効化)。zj tex を使う前に:"
    warn "  cd ~/workspace/LaTeX-Work && docker compose up -d --build"
fi

# --- 完了 -------------------------------------------------------------------
log "セットアップ完了"
cat <<DONE

  次の手順:
    1. 新しいシェルを開く(または: source ~/.bashrc)
    2. zj py

  初回の zj py 起動時に、LazyVim が LSP(basedpyright/ruff)と
  treesitter パーサを自動インストールします(1回だけ時間がかかります)。

  ・タブ切替 : Ctrl+t → 1(work)/ 2(monitor)
  ・nvim の取り消し=u / やり直し=Ctrl+r(Ctrl+Z は無効化済み)
  ・ファイル検索=Space Space / ツリー=Space e

DONE
