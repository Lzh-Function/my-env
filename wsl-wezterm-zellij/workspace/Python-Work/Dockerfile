# syntax=docker/dockerfile:1
FROM python:3.13.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/
ENV UV_PYTHON_PREFERENCE=only-system \
    UV_LINK_MODE=copy

# --- editor & multiplexer: Neovim/Zellij run inside the container itself ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl unzip build-essential \
        ripgrep fd-find nodejs npm btop \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd

RUN curl -Lo /tmp/nvim.tar.gz \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz \
    && tar xzf /tmp/nvim.tar.gz -C /opt \
    && ln -s /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim \
    && rm /tmp/nvim.tar.gz

# lazygit: LazyVim auto-enables <leader>gg/<leader>gG once this is on PATH, no config needed
RUN LAZYGIT_VERSION="$(curl -s "https://api.github.com/repos/jesseduffield/lazygit/releases/latest" \
        | grep -Po '"tag_name": "v\K[^"]*')" \
    && curl -Lo /tmp/lazygit.tar.gz \
        "https://github.com/jesseduffield/lazygit/releases/download/v${LAZYGIT_VERSION}/lazygit_${LAZYGIT_VERSION}_Linux_x86_64.tar.gz" \
    && tar xf /tmp/lazygit.tar.gz -C /tmp lazygit \
    && install /tmp/lazygit /usr/local/bin/lazygit \
    && rm /tmp/lazygit.tar.gz /tmp/lazygit

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && cargo install zellij --locked

# Container-only zellij config (no clip.exe: no WSL interop in here)
COPY zellij/ /root/.config/zellij/

WORKDIR /workspace/Python-Work
CMD ["sleep", "infinity"]
