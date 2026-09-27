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
mkdir -p "${HOME}/.local/bin"


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

echo
echo "CLI setup complete."
