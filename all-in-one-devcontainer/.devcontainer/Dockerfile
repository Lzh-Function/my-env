# ================================================================
# Base image
# ================================================================
#
# Microsoft が提供する Dev Containers 用 Ubuntu 24.04 base image。
#
# `vscode` という一般ユーザーが最初から用意されているため、
# root ではなく通常ユーザーで開発できます。
#
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04


# ================================================================
# OS packages
# ================================================================
#
# Python / Rust / Node.js 自体は devcontainer.json の Features から
# インストールします。
#
# Dockerfile では主に、
#
#   - C/C++ toolchain
#   - LaTeX
#   - CLI utilities
#
# をインストールします。
#
RUN apt-get update && apt-get install -y --no-install-recommends \
    \
    # ------------------------------------------------------------
    # General development utilities
    # ------------------------------------------------------------
    git \
    curl \
    wget \
    ca-certificates \
    jq \
    ripgrep \
    fd-find \
    less \
    unzip \
    zip \
    file \
    tree \
    \
    # ------------------------------------------------------------
    # C / C++
    # ------------------------------------------------------------
    build-essential \
    gcc \
    g++ \
    clang \
    clangd \
    gdb \
    lldb \
    cmake \
    ninja-build \
    pkg-config \
    \
    # ------------------------------------------------------------
    # LaTeX
    # ------------------------------------------------------------
    latexmk \
    biber \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-pictures \
    texlive-science \
    texlive-bibtex-extra \
    texlive-fonts-recommended \
    texlive-lang-japanese \
    texlive-xetex \
    texlive-luatex \
    \
    # Python source code を LaTeX minted 等から扱う場合にも便利
    python3-pygments \
    \
    # PDF inspection / conversion utilities
    ghostscript \
    poppler-utils \
    \
    # ------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# Ubuntu では fd コマンドが fdfind という名前で入るため、
# 一般的な `fd` コマンド名でも使えるようにします。
RUN ln -sf /usr/bin/fdfind /usr/local/bin/fd


# ================================================================
# uv
# ================================================================
#
# Astral 公式の distroless image から uv / uvx の binary だけを
# コピーします。
#
# Python package は pip を直接使わず、
# 各 project の pyproject.toml + uv で管理する想定です。
#
COPY --from=ghcr.io/astral-sh/uv:0.12.17 \
    /uv /uvx /usr/local/bin/


# ================================================================
# Persistent agent directories
# ================================================================
#
# 以下のディレクトリは devcontainer.json で Docker named volume を
# mount します。
#
# mount 前にディレクトリを作成し vscode 所有にしておくことで、
# volume 初期化時の permission 問題を避けます。
#
RUN mkdir -p \
        /home/vscode/.codex \
        /home/vscode/.claude \
        /home/vscode/.local/share/opencode \
        /home/vscode/.config/opencode \
        /home/vscode/.local/bin \
    && chown -R vscode:vscode \
        /home/vscode/.codex \
        /home/vscode/.claude \
        /home/vscode/.local \
        /home/vscode/.config


# ================================================================
# Default environment
# ================================================================
#
# npm --prefix ~/.local でインストールする CLI を見つけられるよう
# ~/.local/bin を PATH に追加します。
#
ENV PATH="/home/vscode/.local/bin:${PATH}"
