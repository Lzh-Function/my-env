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
    # Rust の cross build (cargo-xwin) が Windows target の link に使う
    # lld / llvm もここで入れておく
    \
    lld \
    llvm \
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
# Headless browser runtime libraries
# ================================================================
#
# Playwright / Chromium を container 内で headless 起動するための
# 実行時ライブラリとフォントです。
#
# UI の検証スクリプト (例: Strata の chat UI を chromium で叩く確認) が
# container 内で完結するように、image 側へ入れておきます。
#
# 実際の browser binary 自体は ~/.cache/ms-playwright へ展開されるため、
# post-create.sh 側でダウンロードします。
#
# パッケージ一覧は `playwright install-deps chromium` が Ubuntu 24.04 で
# 選択する集合と同じです。--no-install-recommends を付けることで
# recommends 経由で GUI stack が余計に増えるのを防ぎます。
#
RUN apt-get update && apt-get install -y --no-install-recommends \
    \
    # ------------------------------------------------------------
    # Chromium 本体が要求する共有ライブラリ
    # ------------------------------------------------------------
    libasound2t64 \
    libatk-bridge2.0-0t64 \
    libatk1.0-0t64 \
    libatspi2.0-0t64 \
    libcairo2 \
    libcups2t64 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0t64 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    \
    # ------------------------------------------------------------
    # Xvfb: display が無い環境で Chromium を起動するための仮想 display
    # ------------------------------------------------------------
    xvfb \
    \
    # ------------------------------------------------------------
    # フォント (欠けていると headless 描画が文字化けする)
    # ------------------------------------------------------------
    libfontconfig1 \
    libfreetype6 \
    fonts-noto-color-emoji \
    fonts-unifont \
    fonts-liberation \
    fonts-ipafont-gothic \
    fonts-wqy-zenhei \
    fonts-tlwg-loma-otf \
    fonts-freefont-ttf \
    xfonts-cyrillic \
    xfonts-scalable \
    \
    # ------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# ================================================================
# ffmpeg
# ================================================================
#
# 画像 / 動画生成の前後処理 (書き出し・concat・音声抽出など) で
# ffmpeg CLI を使うため、system の ffmpeg を入れておきます。
#
# Python 側の torchvision / torchaudio は自前ビルドの codec を使うため、
# ここに入れるものとは別物です。
#
RUN apt-get update && apt-get install -y \
        ffmpeg \
        libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*


# ================================================================
# CUDA Toolkit
# ================================================================
#
# Strata の engine を container 内で build するための CUDA toolkit です。
# 実行自体は host 側の NVIDIA driver と nvidia-container-toolkit が
# 提供してくれるため、driver 自体は image に含めません。
#
# 注意:
#
#   - cuda-toolkit-13-0 は metapackage で、nsight / openjdk / systemd 等を
#     recommends ごと取り込みます (~7 GB)。Strata の build に必要な
#     compiler / headers / libraries をまとめて確保できるため、
#     ここでは recommends を落とさずに入れます。
#
#   - /usr/local/cuda/bin は PATH に追加しません。
#     Strata の setup.py:find_nvcc() は PATH の他に
#     /usr/local/cuda* を glob して nvcc を探すため、
#     PATH から解決できなくても build に影響しません。
#     手元で nvcc を叩きたい場合は
#     /usr/local/cuda-13.0/bin/nvcc を直接指定してください。
#
#   - apt repository は NVIDIA の rolling repository のため、
#     minor version は build 時に動きます。
#     再現性を固定したい場合は package 名に version を指定します。
#
RUN set -eux; \
    \
    # NVIDIA 公式の signing key を keyring として配置します。
    # 既存 container に入っている keyring と sha256 が一致するファイルです。
    curl -fsSL \
        https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-archive-keyring.gpg \
        -o /usr/share/keyrings/cuda-archive-keyring.gpg; \
    \
    printf '%s\n' \
        'deb [signed-by=/usr/share/keyrings/cuda-archive-keyring.gpg] https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/ /' \
        > /etc/apt/sources.list.d/cuda-ubuntu2404-x86_64.list; \
    \
    # cuda-toolkit-13-0 は systemd / dbus 等を引き込むため、
    # build 中に invoke-rc.d が service を起動しようとして失敗します。
    # policy-rc.d を一時的に置くことで起動だけをスキップし、
    # container 実行時の挙動には手を入れないようにします。
    printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d; \
    chmod +x /usr/sbin/policy-rc.d; \
    \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get install -y \
        -o Dpkg::Options::=--force-confdef \
        -o Dpkg::Options::=--force-confold \
        cuda-toolkit-13-0; \
    \
    rm -f /usr/sbin/policy-rc.d; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*


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
