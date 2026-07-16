#!/usr/bin/env bash
# =============================================================================
#  WSL(Ubuntu)側セットアップ  ── まっさらな WSL から zj py まで一気通貫
#
#  役割分担:
#    - 設定ファイル(.bashrc / nvim / zellij / Dockerfile / compose.yml)は chezmoi(my-env リポジトリ)が展開
#    - Neovim / Zellij は Python-Work・LaTeX-Work の各コンテナ内にも入っており、
#      `zj py` / `zj tex` はホストではなくコンテナの中で編集・実行する(plain だけホスト実行)
#    - このスクリプトは「ツール導入 + Docker + chezmoi apply + uv 初期化 + build」
#
#  非対話性: sudo パスワードと、SSH 鍵未登録時の GitHub 登録待ち以外は無人。
#
#  使い方:
#     bash setup-wsl.sh              # Python と LaTeX の両環境をビルドして zj py / zj tex まで
# =============================================================================
set -euo pipefail

REPO_URL='git@github.com:Lzh-Function/my-env.git'
SOURCE_SUB='wsl-wezterm-zellij'

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

WORKSPACE="$HOME/workspace"
PYDIR="$WORKSPACE/Python-Work"
TEXDIR="$WORKSPACE/LaTeX-Work"

# --- 0. sudo 認証を維持 -----------------------------------------------------
log "事前チェック"
command -v sudo >/dev/null || die "sudo が見つかりません。"
sudo -v || die "sudo 認証に失敗。"
( while true; do sudo -n true; sleep 50; kill -0 "$$" 2>/dev/null || exit; done ) 2>/dev/null &
trap 'kill %1 2>/dev/null || true' EXIT

export DEBIAN_FRONTEND=noninteractive

# --- 1. 基本パッケージ ------------------------------------------------------
log "基本パッケージのインストール"
sudo apt-get update -y
sudo apt-get install -y --no-install-recommends \
    ca-certificates curl git build-essential \
    btop ripgrep fd-find nodejs npm unzip
mkdir -p "$HOME/.local/bin"
[[ -e "$HOME/.local/bin/fd" ]] || ln -s "$(command -v fdfind)" "$HOME/.local/bin/fd" 2>/dev/null || true

# --- 2. Docker(docker-ce)公式手順 -----------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    log "Docker Engine をインストール(公式手順)"
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    sudo chmod a+r /etc/apt/keyrings/docker.asc
    sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    sudo apt-get update -y
    sudo apt-get install -y \
        docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

log "Docker デーモンを起動 & ソケット権限を付与"
sudo systemctl enable --now docker 2>/dev/null || sudo service docker start 2>/dev/null || true
sleep 2
sudo chmod 666 /var/run/docker.sock 2>/dev/null || true
docker version >/dev/null 2>&1 || warn "docker がまだ応答しません。systemd 有効化(/etc/wsl.conf)や 'sudo service docker start' を確認。"

# --- 3. Rust(rustup)+ cargo + Zellij --------------------------------------
if ! command -v cargo >/dev/null 2>&1; then
    log "Rust(rustup)を非対話インストール"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
fi
[[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v zellij >/dev/null 2>&1; then
    log "Zellij を cargo でインストール(コンパイルに数分)"
    cargo install zellij --locked
fi

# --- 4. Neovim(tarball)----------------------------------------------------
if ! command -v nvim >/dev/null 2>&1; then
    log "Neovim をインストール"
    tmp="$(mktemp -d)"
    curl -Lo "$tmp/nvim.tar.gz" \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
    sudo tar xzf "$tmp/nvim.tar.gz" -C /opt
    sudo ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim
    rm -rf "$tmp"
fi

# --- 4.5. lazygit(GitHub release tarball)-----------------------------------
# LazyVimは lazygit が PATH 上にあれば <leader>gg / <leader>gG を自動で有効化する
# (~/.local/share/nvim/lazy/LazyVim/lua/lazyvim/config/keymaps.lua)。設定側の変更は不要。
if ! command -v lazygit >/dev/null 2>&1; then
    log "lazygit をインストール"
    LAZYGIT_VERSION="$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" \
        | grep -Po '"tag_name": "v\K[^"]*')"
    tmp="$(mktemp -d)"
    curl -Lo "$tmp/lazygit.tar.gz" \
        "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz"
    tar xf "$tmp/lazygit.tar.gz" -C "$tmp" lazygit
    install "$tmp/lazygit" "$HOME/.local/bin/lazygit"
    rm -rf "$tmp"
fi

# --- 5. chezmoi(snap)------------------------------------------------------
if ! command -v chezmoi >/dev/null 2>&1; then
    log "chezmoi を snap でインストール"
    sudo snap install chezmoi --classic \
        || die "snap install に失敗。WSL で systemd(/etc/wsl.conf の [boot] systemd=true)が有効か確認してください。"
fi

# --- 6. SSH 鍵(GitHub 認証)------------------------------------------------
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
sort -u "$HOME/.ssh/known_hosts" -o "$HOME/.ssh/known_hosts" 2>/dev/null || true

if ! ssh -o BatchMode=yes -o StrictHostKeyChecking=no -T git@github.com 2>&1 | grep -qi 'successfully authenticated'; then
    if [[ ! -f "$HOME/.ssh/id_ed25519" ]]; then
        log "SSH 鍵を生成"
        ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -q -C "$(whoami)@wsl"
    fi
    echo
    warn "GitHub にSSH公開鍵を登録してください(Settings → SSH and GPG keys → New SSH key):"
    echo "-----------------------------------------------------------------"
    cat "$HOME/.ssh/id_ed25519.pub"
    echo "-----------------------------------------------------------------"
    read -rp "登録が終わったら Enter を押して続行..." _
fi

# --- 7. chezmoi init → source dir 固定 → apply -----------------------------
log "chezmoi で my-env を clone"
chezmoi init "$REPO_URL"

log "source dir を $SOURCE_SUB に固定"
mkdir -p "$HOME/.config/chezmoi"
cat > "$HOME/.config/chezmoi/chezmoi.toml" <<EOF
sourceDir = "$HOME/.local/share/chezmoi/$SOURCE_SUB"
EOF
echo "source-path = $(chezmoi source-path)"

log "chezmoi apply(Linux では wezterm 以外=.bashrc / nvim / zellij / workspace 下の Dockerfile 等を展開)"
chezmoi apply

# apply 後に配置された .bashrc の PATH 等を今のシェルにも反映
[[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# --- 8. pdfview ラッパー(SumatraPDF)-------------------------------------
# nvim の keymaps.lua(chezmoi 管理)が ~/.local/bin/pdfview を呼ぶため用意。
WINUSER="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r' || true)"
[[ -z "$WINUSER" ]] && WINUSER="CHANGE_ME"
cat > "$HOME/.local/bin/pdfview" <<EOF
#!/usr/bin/env bash
set -euo pipefail
SUMATRA="/mnt/c/Users/${WINUSER}/AppData/Local/SumatraPDF/SumatraPDF.exe"
pdf_win="\$(wslpath -w "\$(realpath "\$1")")"
"\$SUMATRA" -reuse-instance "\$pdf_win" >/dev/null 2>&1 &
disown
EOF
chmod +x "$HOME/.local/bin/pdfview"
[[ "$WINUSER" == "CHANGE_ME" ]] && warn "Windows ユーザー名を検出できず。~/.local/bin/pdfview の SUMATRA パスを手で修正してください。"

# --- 9. Neovim プラグイン同期(headless)-----------------------------------
log "Neovim プラグインを同期(LSP/treesitter は初回 zj py 起動時に自動完了)"
nvim --headless "+Lazy! sync" +qa 2>/dev/null || warn "Lazy sync で警告。続行します。"

# --- 10. Docker ビルド + uv 初期化 -----------------------------------------
# Dockerfile / compose.yml / .dockerignore / .latexmkrc は chezmoi apply(手順7)で
# 既に $PYDIR / $TEXDIR に展開済み(このリポジトリの workspace/ 以下が source)。
docker version >/dev/null 2>&1 || die "docker が使えません(手順2の起動/権限を確認)。"

log "Python コンテナをビルド"
( cd "$PYDIR" && docker compose build && docker compose up -d )

log "コンテナ内で uv 初期化(.venv 生成)"
( cd "$PYDIR" && docker compose exec -T py bash -lc '
    cd /workspace/Python-Work
    [ -f pyproject.toml ] || uv init --bare 2>/dev/null || uv init --name py-app
    uv add numpy pandas scikit-learn
' ) || warn "uv 初期化で警告。後で: cd ~/workspace/Python-Work && docker compose exec py uv add numpy pandas scikit-learn"

log "LaTeX(texlive)コンテナをビルド(イメージが大きいので初回は時間がかかります)"
( cd "$TEXDIR" && docker compose build && docker compose up -d )

# --- 完了 -------------------------------------------------------------------
log "セットアップ完了"
cat <<'DONE'

  最後に、シェル設定を反映してください:

      source ~/.bashrc

  その後:

      zj py     # コンテナに入り、コンテナ内 zellij で work タブ(nvim+shell)+ monitor タブ(btop)
      zj tex    # 同上、LaTeX-Work コンテナ側(latexmk -pvc -cd <文書名>/main.tex)
      zj        # plain レイアウト(ホスト側 nvim、コンテナなしの軽い編集用)

  初回 zj py / zj tex 起動時に、コンテナ内の LazyVim が LSP と treesitter を
  自動インストールします(1回だけ時間がかかります)。

DONE
