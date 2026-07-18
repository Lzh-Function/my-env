#!/usr/bin/env bash
# =============================================================================
#  SSHサーバー(Ubuntu, WSLではない素のLinux)側セットアップ
#  ── まっさらな Ubuntu から zj (plainレイアウト) まで一気通貫
#
#  役割分担:
#    - 設定ファイル(nvim / zellij / zjrc.sh)は chezmoi(my-env リポジトリ)が展開
#    - ~/.bashrc 自体はchezmoiの対象外(.chezmoiignore)。このホストは「まっさら」
#      とは限らず、既存の ~/.bashrc を上書きしたくないため、chezmoi apply後に
#      zj/zjdel/zjdoctorを読み込む1行だけを本スクリプトが冪等に追記する
#      (既に追記済みなら何もしない)
#    - Docker/workspace(Python-Work・LaTeX-Work)は WSL専用。.chezmoiignore が
#      env WSL_DISTRO_NAME の有無を見て自動判定するので、このホストには一切
#      展開されない(このスクリプトもDockerには一切触れない)
#    - このスクリプトは「ツール導入 + chezmoi apply + ~/.bashrc への1行追記」のみ
#
#  非対話性: sudo パスワードと、SSH 鍵未登録時の GitHub 登録待ち以外は無人。
#
#  使い方:
#     bash setup_ssh.sh
# =============================================================================
set -euo pipefail

REPO_URL='git@github.com:Lzh-Function/my-env.git'
SOURCE_SUB='wsl-wezterm-zellij'

log()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m[warn] %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m[error] %s\033[0m\n' "$*" >&2; exit 1; }

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

# --- 2. Rust(rustup)+ cargo + Zellij --------------------------------------
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

# --- 3. Neovim(tarball)----------------------------------------------------
if ! command -v nvim >/dev/null 2>&1; then
    log "Neovim をインストール"
    tmp="$(mktemp -d)"
    curl -Lo "$tmp/nvim.tar.gz" \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
    sudo tar xzf "$tmp/nvim.tar.gz" -C /opt
    sudo ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim
    rm -rf "$tmp"
fi

# --- 4. chezmoi(公式インストーラ)-------------------------------------------
# snapが無い/使えない素のサーバーでも動くよう、公式スクリプトで ~/.local/bin に置く。
if ! command -v chezmoi >/dev/null 2>&1; then
    log "chezmoi をインストール(公式スクリプト)"
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
fi

# --- 5. SSH 鍵(GitHub 認証)------------------------------------------------
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true
sort -u "$HOME/.ssh/known_hosts" -o "$HOME/.ssh/known_hosts" 2>/dev/null || true

if ! ssh -o BatchMode=yes -o StrictHostKeyChecking=no -T git@github.com 2>&1 | grep -qi 'successfully authenticated'; then
    if [[ ! -f "$HOME/.ssh/id_ed25519" ]]; then
        log "SSH 鍵を生成"
        ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/id_ed25519" -q -C "$(whoami)@$(hostname)"
    fi
    echo
    warn "GitHub にSSH公開鍵を登録してください(Settings → SSH and GPG keys → New SSH key):"
    echo "-----------------------------------------------------------------"
    cat "$HOME/.ssh/id_ed25519.pub"
    echo "-----------------------------------------------------------------"
    read -rp "登録が終わったら Enter を押して続行..." _
fi

# --- 6. chezmoi init → source dir 固定 → apply -----------------------------
log "chezmoi で my-env を clone"
chezmoi init "$REPO_URL"

log "source dir を $SOURCE_SUB に固定"
mkdir -p "$HOME/.config/chezmoi"
cat > "$HOME/.config/chezmoi/chezmoi.toml" <<EOF
sourceDir = "$HOME/.local/share/chezmoi/$SOURCE_SUB"
EOF
echo "source-path = $(chezmoi source-path)"

log "chezmoi apply(SSHサーバーとして判定: WSL_DISTRO_NAME 未設定なので nvim / zellij / zjrc.sh のみ展開。~/.bashrc自体・Docker/workspaceは対象外)"
chezmoi apply

[[ -f "$HOME/.cargo/env" ]] && . "$HOME/.cargo/env"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# --- 6.5. ~/.bashrc に zj/zjdel/zjdoctorの読み込み行だけ追記 ----------------
# ~/.bashrc自体はchezmoiの対象外なので、既存の内容(このホストが「まっさら」
# ではなく既に手元で使われていた場合の独自設定など)を一切上書きしない。
ZJRC_SOURCE_LINE='[ -f "$HOME/.config/zj/zjrc.sh" ] && . "$HOME/.config/zj/zjrc.sh"'
touch "$HOME/.bashrc"
if grep -qxF "$ZJRC_SOURCE_LINE" "$HOME/.bashrc"; then
    log "~/.bashrc は既に zjrc.sh を読み込み済み(追記不要)"
else
    log "~/.bashrc に zj / zjdel / zjdoctor の読み込み行を追記(既存の内容はそのまま残す)"
    {
        printf '\n# my-env: zj / zjdel / zjdoctor ------------------------------------------\n'
        printf '%s\n' "$ZJRC_SOURCE_LINE"
    } >> "$HOME/.bashrc"
fi

# --- 7. Neovim プラグイン同期(headless)-----------------------------------
log "Neovim プラグインを同期(LSP/treesitterは初回 zj 起動時に自動完了)"
nvim --headless "+Lazy! sync" +qa 2>/dev/null || warn "Lazy sync で警告。続行します。"

# --- 完了 -------------------------------------------------------------------
log "セットアップ完了"
cat <<'DONE'

  最後に、シェル設定を反映してください:

      source ~/.bashrc

  その後:

      zj        # plain レイアウト(nvim + shell の2ペイン)

  Docker型の zj py / zj tex はWSLホスト専用なので、このサーバーには存在しません。
  (このホストの zj / zjdel は WSL側と同名だが中身は別物 ── 常にplainレイアウトのみ)

DONE
