FROM texlive/texlive:latest

# --- editor & multiplexer: Neovim/Zellij run inside the container itself ---
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl unzip build-essential \
        ripgrep fd-find nodejs npm btop \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd

RUN curl -Lo /tmp/nvim.tar.gz \
        https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz \
    && tar xzf /tmp/nvim.tar.gz -C /opt \
    && ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim \
    && rm /tmp/nvim.tar.gz

ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y \
    && cargo install zellij --locked

# Container-only zellij config (no clip.exe: no WSL interop in here)
COPY zellij/ /root/.config/zellij/

WORKDIR /workspace/LaTeX-Work
CMD ["sleep", "infinity"]
