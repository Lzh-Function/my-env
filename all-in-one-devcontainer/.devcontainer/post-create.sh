#!/usr/bin/env bash

set -euo pipefail

echo "============================================================"
echo "Setting up AI coding agents"
echo "============================================================"


# ------------------------------------------------------------
# NVM / Node.js
# ------------------------------------------------------------
#
# Dev Containers Node Feature は通常 nvm を使用します。
#
# postCreateCommand の非interactive shellでも npm が確実に
# 利用できるよう、nvm.sh が存在すれば明示的に読み込みます。
#
if [[ -n "${NVM_DIR:-}" && -s "${NVM_DIR}/nvm.sh" ]]; then
    # shellcheck disable=SC1091
    source "${NVM_DIR}/nvm.sh"
fi


echo
echo "[Node.js]"
node --version
npm --version


# ------------------------------------------------------------
# Local npm prefix
# ------------------------------------------------------------
#
# coding agent を system-wide /usr/local へ入れるのではなく、
#
#   ~/.local/bin
#   ~/.local/lib
#
# 以下へインストールします。
#
# sudo npm install -g は使用しません。
#
# さらに ~/.npmrc にも prefix を書き込んでおきます。
# これをしないと npm install -g の既定先が nvm の
#
#   /usr/local/share/nvm/versions/node/<version>
#
# のままになり、CLI 組み込みの自己 update (codex update など) だけが
# nvm 側へ新版を入れてしまいます。
# devcontainer.json の remoteEnv で ~/.local/bin が PATH の先頭に
# 来るため、結果として update が反映されず古い version が
# 残り続ける (codex update を繰り返しても更新されない) 状態になります。
#
# prefix を user config に固定すると、
# post-create.sh のインストールと自己 update が同じ場所を
# 指すようになります。
#
mkdir -p "${HOME}/.local/bin"

npm config set prefix "${HOME}/.local"


# ------------------------------------------------------------
# 任意 step の実行ヘルパー
# ------------------------------------------------------------
#
# 以下は network 依存で、失敗しても container 自体は使える step です。
# 1 回だけ再試行し、それでも失敗した場合は warn して先に進みます。
#
# container 作成自体を失敗させないためのガードです。
# 失敗した step は container 内で
#
#   bash /workspace/.devcontainer/post-create.sh
#
# と再実行できます (既存の step はすべて再実行安全)。
#
run_optional() {
    local label="$1"
    shift

    echo
    echo "[${label}]"

    if "$@"; then
        return 0
    fi

    echo "WARN: '${label}' failed. retrying once..." >&2
    sleep 5

    if "$@"; then
        return 0
    fi

    echo "WARN: '${label}' failed twice. continuing without it." >&2
    return 0
}


# ------------------------------------------------------------
# uv が管理する Python
# ------------------------------------------------------------
#
# project の .venv は uv が Python をダウンロードして作ります。
# 事前に 3.12 を入れておくと、container 作成直後の venv 作成が
# network 無しで完結します。
#
run_optional "uv Python 3.12" uv python install 3.12

# uv 管理の 3.12 を python3.12 として直接叩けるようにします。
# project の影響を受けないよう $HOME で解決します。
#
py312="$(cd "${HOME}" && uv python find 3.12 2>/dev/null || true)"
if [[ -n "${py312}" && -x "${py312}" ]]; then
    ln -sfn "${py312}" "${HOME}/.local/bin/python3.12"
fi


# ------------------------------------------------------------
# Codex
# ------------------------------------------------------------
#
# OpenAI Codex CLI
#
echo
echo "[Codex]"
npm install -g --prefix "${HOME}/.local" @openai/codex


# ------------------------------------------------------------
# Claude Code
# ------------------------------------------------------------
#
# Anthropic Claude Code CLI
#
echo
echo "[Claude Code]"
npm install -g --prefix "${HOME}/.local" @anthropic-ai/claude-code


# ------------------------------------------------------------
# OpenCode
# ------------------------------------------------------------
#
# OpenCode CLI
#
echo
echo "[OpenCode]"
npm install -g --prefix "${HOME}/.local" @opencode/cli


# opencode は opencode2 でも呼べるようにしておきます。
# 同じ binary への別名で、呼び分け用の shell alias 代わりです。
#
(
    cd "${HOME}/.local/bin"
    ln -sfn ../lib/node_modules/@opencode/cli/bin/opencode.exe opencode2
)


# ------------------------------------------------------------
# Hugging Face CLI
# ------------------------------------------------------------
#
# uv tool で独立した環境に hf コマンドをインストールします。
# executable は ~/.local/bin に配置されます。
#
echo
echo "[Hugging Face CLI]"
uv tool install hf


# ------------------------------------------------------------
# Google Colab CLI
# ------------------------------------------------------------
#
# host に GPU が無い時に、Colab の GPU を借りて実行するための CLI です。
# hf と同じく uv tool で独立環境に入れます。
#
run_optional "Google Colab CLI" uv tool install google-colab-cli


# ------------------------------------------------------------
# Rust CLI
# ------------------------------------------------------------
#
# dust      : du の代わり (disk usage の可視化)
# cargo-xwin: Windows target への cross build (AppAudioRecorder 用)
#
# CARGO_HOME / RUSTUP_HOME は Rust Feature が containerEnv で
# 設定済みのため、実行ユーザーが vscode でも
# /usr/local/cargo へ書き込めます (rustlang group 所属)。
# 未設定の場合に備えて、同じ場所を明示的に指定します。
#
export CARGO_HOME="${CARGO_HOME:-/usr/local/cargo}"
export RUSTUP_HOME="${RUSTUP_HOME:-/usr/local/rustup}"
export PATH="${CARGO_HOME}/bin:${PATH}"

install_crate() {
    local bin="$1"
    local crate="$2"

    if command -v "${bin}" >/dev/null 2>&1; then
        echo
        echo "[${bin}] already installed: $(command -v "${bin}")"
        return 0
    fi

    if ! command -v cargo >/dev/null 2>&1; then
        echo
        echo "WARN: cargo not found. skip '${crate}'." >&2
        return 0
    fi

    # --locked: crates.io の依存解決を lock file に固定し、
    #           build 失敗しにくい状態だけ使います。
    run_optional "cargo install ${crate}" cargo install --locked "${crate}"
}

install_crate dust du-dust
install_crate cargo-xwin cargo-xwin


# ------------------------------------------------------------
# Playwright Chromium
# ------------------------------------------------------------
#
# Chromium を動かすための system library は Dockerfile 側で
# すでに導入済みです。ここでは browser binary 自体を
# ~/.cache/ms-playwright へダウンロードします。
#
# version を固定している理由:
#   playwright 1.63.0 は chromium build 1243
#   (Chrome for Testing 153.0.8010.12) を配布します。
#   UI 検証スクリプトがこの browser 構成で確認済みなので、
#   floating にして browser が勝手に変わらないようにします。
#
# npx は package を一時 cache に展開するだけで、
# global な node_modules を汚しません。
#
PLAYWRIGHT_VERSION="1.63.0"

if find "${HOME}/.cache/ms-playwright" -maxdepth 1 -type d \
        -name 'chromium-*' 2>/dev/null | grep -q .; then

    echo
    echo "[Playwright] chromium already installed, skip download"

elif ! command -v npx >/dev/null 2>&1; then

    echo
    echo "WARN: npx not found. skip Playwright browser download." >&2

else

    # system library は image 側にあるため --with-deps は付けません。
    run_optional "Playwright chromium ${PLAYWRIGHT_VERSION}" \
        npx --yes "playwright@${PLAYWRIGHT_VERSION}" install chromium

fi


# ------------------------------------------------------------
# Verification
# ------------------------------------------------------------

echo
echo "============================================================"
echo "Installed versions"
echo "============================================================"

codex --version || true
claude --version || true
opencode --version || true
hf --help >/dev/null
echo "hf CLI available"

colab --help >/dev/null 2>&1 \
    && echo "colab CLI available" \
    || echo "WARN: colab CLI unavailable" >&2

dust --version 2>/dev/null || echo "WARN: dust unavailable" >&2
cargo-xwin --version 2>/dev/null || echo "WARN: cargo-xwin unavailable" >&2

if find "${HOME}/.cache/ms-playwright" -maxdepth 1 -type d \
        -name 'chromium-*' 2>/dev/null | grep -q .; then
    echo "playwright chromium available"
else
    echo "WARN: playwright chromium unavailable" >&2
fi

echo
echo "CLI setup complete."
