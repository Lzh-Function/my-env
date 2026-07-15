# WSL2-WezTerm-Zellij環境

## VScodeでよくね？
ただでさえwslの起動はメモリ食うのに、VScodeを被せて起動したときのリソース消費が激しい。スペックが足りないノートPCにおいてマルチタスクするためにも、軽量でありながらVScode-likeなターミナル環境を求めて採用。\
とりあえず用途はPython-WorkとLaTeX-Workを想定。


## Tutorial

### 1. WSL2のクリーンインストール
きったねえWSL2環境をまっさらにしてからもう一回作りましょう。\
```
@powershell
$ wsl --shutdown
$ wsl -l -v  # ディストリビューションの確認
$ wsl --unregister ubuntu # たぶんubuntu

# 終わったら「アプリと機能」からUbuntuをアンインストール
$ wsl --install ubunutu # 多分ubuntu　(wsl -l -oで確認可能)
```

### 2. WezTermのインストール
```
@powershell
$ winget install wez.wezterm

# Nerd Font
$ winget install -e --id DEVCOM.JetBrainsMonoNerdFont

# .luaファイル
$ New-Item -Path "$env:USERPROFILE\.wezterm.lua" -ItemType File -Force
$ notepad "$env:USERPROFILE\.wezterm.lua"

# .wezterm.luaの内容をコピペ
```
ここまでで、WezTermを開くと自動でWSLが起動するように。

### 3. WSL側でのセットアップ
```
$ sudo apt update

# リソース監視のためのbtop
$ sudo apt install -y btop git curl build-essential

# uv
$ curl -LsSf https://astral.sh/uv/install.sh | sh
$ source $HOME/.local/bin/env

# Zellijのためのrust
$ curl https://sh.rustup.rs -sSf | sh
$ . "$HOME/.cargo/env"

# Zellij
$ cargo install zellij

# NeoVim
$ curl -LO https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz
$ sudo tar xzf nvim-linux-x86_64.tar.gz -C /opt
$ sudo ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim

# LazyVimによってNeoVimを進化させる
$ git clone https://github.com/LazyVim/starter ~/.config/nvim
$ rm -rf ~/.config/nvim/.git

# nvim起動、設定インポート
$ nvim
# :LazyExtraを実行 → lang.python と lang.tex を xキーで有効化
# qでquit
```

### 4. workspace用意（ご自由に）
```
$ mkdir ~/workspace
$ cd ~/workspace
$ mkdir Python-Work
$ mkdir LaTeX-Work
```

### 5. dockerを入れよう
```
# https://docs.docker.com/engine/install/ubuntu/
$ sudo apt update
$ sudo apt install ca-certificates curl
$ sudo install -m 0755 -d /etc/apt/keyrings
$ sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
$ sudo chmod a+r /etc/apt/keyrings/docker.asc
$ sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
$ sudo apt update
$ sudo apt install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# このままだと使用権限が通らないので権限変更
$ sudo chmod 666 /var/run/docker.sock
```

### 6. Python作業環境セットアップ
`Python-Work`ディレクトリ直下に`.venv/pyproject.toml/uv.lock/Dockerfile/compose.yml/.dockerignore`が置かれる構成です。
