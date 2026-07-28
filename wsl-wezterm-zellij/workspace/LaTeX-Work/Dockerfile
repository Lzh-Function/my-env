FROM texlive/texlive:latest

# --- editor & multiplexer: Neovim/Zellij run inside the container itself ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl unzip build-essential sudo \
        ripgrep fd-find nodejs npm btop \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd

RUN curl -Lo /tmp/nvim.tar.gz \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz \
    && tar xzf /tmp/nvim.tar.gz -C /opt \
    && ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim \
    && rm /tmp/nvim.tar.gz

# lazygit: LazyVim auto-enables <leader>gg/<leader>gG once this is on PATH, no config needed
RUN LAZYGIT_VERSION="$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" \
        | grep -Po '"tag_name": "v\K[^"]*')" \
    && curl -Lo /tmp/lazygit.tar.gz \
        "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz" \
    && tar xf /tmp/lazygit.tar.gz -C /tmp lazygit \
    && install /tmp/lazygit /usr/local/bin/lazygit \
    && rm /tmp/lazygit.tar.gz /tmp/lazygit

# fastfetch: shows a logo + system info banner when the shell pane starts (see zellij/layouts)
RUN curl -Lo /tmp/fastfetch.tar.gz \
        "https://github.com/fastfetch-cli/fastfetch/releases/latest/download/fastfetch-linux-amd64.tar.gz" \
    && tar xzf /tmp/fastfetch.tar.gz -C /tmp \
    && install /tmp/fastfetch-linux-amd64/usr/bin/fastfetch /usr/local/bin/fastfetch \
    && rm -rf /tmp/fastfetch.tar.gz /tmp/fastfetch-linux-amd64

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && cargo install zellij --locked

# 非rootユーザー(WSLホスト側のUID/GIDに揃える。bind mountで共有するファイルの
# 所有者を一致させ、コンテナ内で作ったファイルがホスト側でroot所有にならないようにする)。
# ベースイメージに既にUID 1000の`texlive`ユーザーがいるので、新規作成ではなく
# リネーム+ホームディレクトリ変更で流用する(UID重複を避けるため)。
# 対話的なパスワード入力が無い環境のため、sudoはNOPASSWDにしてある。
RUN usermod -l function -d /home/function -m texlive \
    && groupmod -n function texlive \
    && echo 'function ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/function \
    && chmod 0440 /etc/sudoers.d/function

# named volumeのマウント先を先に作ってchownしておく。Dockerが作成する前だと
# マウントポイントがroot所有になり、非rootユーザーが書き込めずLazy syncが
# "Permission denied" → 対話的な"Press any key"待ちでハングする。
RUN mkdir -p /home/function/.local/share/nvim /home/function/.local/state/nvim /home/function/.cache/nvim \
    && chown -R function:function /home/function/.local /home/function/.cache

# Container-only zellij config (no clip.exe: no WSL interop in here)
COPY --chown=function:function zellij/ /home/function/.config/zellij/

WORKDIR /workspace/LaTeX-Work
USER function
CMD ["sleep", "infinity"]
