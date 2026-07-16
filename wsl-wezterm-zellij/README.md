# WSL2-WezTerm-Zellij環境

## Quick Start

`chezmoi apply`済み・Dockerイメージもビルド済みならこれだけ:

```
zj          # ホスト側 Neovim + Zellij(plain: コンテナなしでさっと編集)
zj py       # Python-Work コンテナに入って編集・実行(nvim + shell、monitorタブにbtop)
zj tex      # LaTeX-Work コンテナに入って編集・実行(同上)

zj py claude    # ↑に加えてagentタブ(3番目)でClaude Codeを起動 (要: 事前にclaude/codexを導入・ログイン。Tutorial 8)
zj tex codex    # ↑に加えてagentタブ(3番目)でCodexを起動
zj py both      # agentタブを上下split(上50%=claude、下50%=codex)
zj claude       # plainレイアウト + agentタブ(2番目)でホスト上のclaudeを起動

zjdel       # ホストの Zellij セッションをリセット
zjdel py    # Python-Work コンテナ内のセッションをリセット
zjdel tex   # LaTeX-Work コンテナ内のセッションをリセット
```

`zj`系はセッション名を固定(`plain`/`py`/`tex`)しているので、同じコマンドを打ち直すと
既存セッションに再接続する。何かを壊したら`zjdel [py|tex]` → `zj [py|tex]`で作り直せばOK
(常に`--layout`付きで作り直すので、壊れた状態が復元されることはない)。

素のUbuntu(SSHサーバー、WSLではない)にこのリポジトリを適用した場合は`zj`(`plain`レイアウト)
のみが使える。`zj py`/`zj tex`はDocker前提なのでそもそも定義されない(後述)。

初回セットアップがまだなら下の「Tutorial」を参照
(WSL: `setup_wsl.sh` / Windows: `setup_windows.ps1` / SSHサーバー: `setup_ssh.sh`で自動化済み)。

## VScodeでよくね？
ただでさえwslの起動はメモリ食うのに、VScodeを被せて起動したときのリソース消費が激しい。スペックが足りないノートPCにおいてマルチタスクするためにも、軽量でありながらVScode-likeなターミナル環境を求めて採用。\
用途はPython-WorkとLaTeX-Workを想定。

## この環境のポイント

- **軽い**: WezTermはただのターミナルなので、VSCode(+WSL Remote)より圧倒的にメモリを食わない。GUIはWezTerm一枚、あとは全部ターミナルの中で完結する。
- **設定は全部chezmoiで一元管理**: `.bashrc`・Neovim(LazyVim)・Zellij・WezTerm・各プロジェクトの`Dockerfile`/`compose.yml`まで、このリポジトリ1つがソース。新しいPCでも`chezmoi init && chezmoi apply`だけで同じ環境が復元できる。
- **編集・実行はコンテナの中で完結**: Python-Work・LaTeX-Workそれぞれ専用のDockerコンテナに、NeovimとZellijを直接インストールしてある。ホストのWSLを汚さず、プロジェクトごとに独立した言語ツールチェーン(uv/pyright、texlive/texlab)の上でLSPも含めて動く。
- **それでも「コンテナなしでさっと編集」もできる**: `zj`(引数なし)だけはホスト側のNeovim/Zellijで動く`plain`レイアウト。ちょっとした設定ファイルを見るだけなら、コンテナを起動する必要はない。
- **セッション名は固定・再接続前提**: `zj py`/`zj tex`は毎回タイムスタンプ付きの新規セッションを作るのではなく、`py`/`tex`という固定名のセッションに`attach --create`する。既にセッションが動いていればそれに繋ぎ直すだけ。
- **Zellijでタブ・ペイン管理、WezTermはタブバーなしの軽量フロントエンドに徹する**: 多重化はZellijに任せ、WezTerm側は`enable_tab_bar = false`・OpenGLフロントエンド・アニメ最小限で低スペック機でも軽快に。
- **同じリポジトリで素のSSHサーバー(Ubuntu)もサポート**: `dot_bashrc`・Zellij設定をchezmoiテンプレート化し、`env "WSL_DISTRO_NAME"`の有無でWSLホストか素のLinuxかを自動判定。Docker/`workspace`はWSL側にしか展開されず、SSHサーバー側は`zj`(plainレイアウト)だけのシンプルな構成になる。
- **Claude Code / Codexをagentタブとして統合(WSLホスト限定)**: `zj [py|tex|] [claude|codex|both]`で、レイアウトに専用タブを1枚追加してエージェントを起動できる。コンテナ側はWSLホストの`$HOME`をそのままbind mountして`HOME`環境変数を上書きするだけなので、コンテナ内に別途インストールし直したり再ログインしたりする必要がない(詳細は「アーキテクチャ」参照)。

## アーキテクチャ

```
Windows (WezTerm)
   └─ WSL2 (Ubuntu)  ※ env WSL_DISTRO_NAME が立っているホスト
        ├─ zj            → ホストの Zellij (session "plain") + ホストの Neovim
        │                  コンテナなしで手早く編集したいとき用
        │
        ├─ zj py         → docker compose exec で Python-Work コンテナに入り、
        │                  コンテナ内の Zellij (session "py") にアタッチ/作成
        │                    - work タブ:   nvim (コンテナ内) + shell (bash)
        │                    - monitor タブ: btop
        │
        └─ zj tex        → 同様に LaTeX-Work コンテナに入る (session "tex")
                             - work タブ:   nvim (コンテナ内) + shell (bash)
                             - monitor タブ: btop

SSHサーバー (素の Ubuntu, WSL_DISTRO_NAME 無し)
   └─ zj               → ホストの Zellij (session "plain") + ホストの Neovim のみ
                          (zj py / zj tex は定義されない。Docker/workspace も展開されない)
```

WSLホストか素のLinux(SSHサーバー)かは、`chezmoi apply`実行時に`env "WSL_DISTRO_NAME"`
(WSL2が自動で設定する環境変数)を見て自動判定している。手動でのフラグ切り替えは不要で、
同じ`chezmoi init && chezmoi apply`をどちらのホストで実行しても、それぞれに適した内容が
展開される。

Neovimの設定(`~/.config/nvim`、LazyVim)はホストとコンテナで共有(bind mount)。
プラグイン本体やLSP/treesitterのインストール先(`~/.local/share/nvim`等)はコンテナごとに
Docker named volumeで持たせているので、コンテナを作り直してもLazy/Masonの再インストールは
基本的に発生しない。

Zellijの設定はホスト用(`dot_config/zellij/`)とコンテナ用(`workspace/*/zellij/`)を分けている。
理由はクリップボード連携(`copy_command "clip.exe"`)がWSL⇔Windows間のinterop前提の機能で、
コンテナの中からは呼べないため。コンテナ側の設定ではこの行を外してある。

各Zellij設定(ホスト・コンテナ双方)は`session_serialization`を明示的に無効化していない
(デフォルトの有効のまま)。そのため`zellij list-sessions`はセッションをkillした後も
しばらく「EXITED - attach to resurrect」として残すが、`zj`/`zjdel`はどちらも
`--layout`付きの`--create`でアタッチするため、古い(壊れた)状態が復元されることはなく、
常にレイアウト通りのまっさらな状態が作られる。

### エージェントタブ(`zj [py|tex|] [claude|codex|both]`、WSLホスト限定)

**前提**: `claude`/`codex`本体のインストールとログインをホスト側で先に済ませておくこと
(Tutorial「8. Claude Code / Codexの導入」参照)。`setup_wsl.sh`はこれを自動化しない。

`dot_bashrc.tmpl`の`_zj_layout()`が、モード(`py`/`tex`/plain)とエージェント指定に応じて
Zellijのレイアウトを**その場でKDL文字列として組み立て**、`zellij --layout-string`で渡す
(エージェント無指定のときは今まで通り静的な`.kdl`ファイルを使うので、既存の`zj py`/
`zj tex`/`zj`の挙動は一切変わらない)。追加されるタブは常に末尾: `py`/`tex`は
work→monitor→**agent**の3番目、plainはedit→**agent**の2番目。`both`指定時はagentタブが
上下split(上50%=claude、下50%=codex)になる。

コンテナ側でclaude/codexを動かす仕組み:
- `workspace/{Python-Work,LaTeX-Work}/compose.yml`がWSLホストの`$HOME`を**同じ絶対パス**で
  コンテナにbind mountする(`${HOME}:${HOME}`)。`~/.local/bin/claude`・`~/.local/bin/codex`
  は`$HOME`配下への**絶対パスシンボリックリンク**なので、`/host-home`のような別パスに
  マウントするとリンク切れになる ── これが同じパスでマウントしている理由。
- agentタブのペインは`HOME=$HOME exec $HOME/.local/bin/claude`(codexも同様)のように、
  そのホームパスを明示して起動する。これでclaude/codexはコンテナ内でもWSLホストの
  `~/.claude`・`~/.claude.json`・`~/.codex`(認証情報・設定・skillsを含む)をそのまま見つけ、
  コンテナ内で再インストールや再ログインをする必要がない。
- **注意**: このbind mountは読み書き可能(`rw`)で、WSLホストの`$HOME`を丸ごと(SSH鍵や
  他プロジェクトも含めて)コンテナ内のrootプロセスに公開する。claude/codexの認証トークン
  更新など書き込みが必要な用途を優先してこの設計にしているが、コンテナ内で実行するものは
  信頼できるコマンドに限定すること。

plain(ホスト側)でのエージェントは単にホストの`claude`/`codex`をそのまま実行するだけで、
bind mountは関与しない。

エージェント付きレイアウトも`--layout`と同様に**セッション作成時にしか効かない**。
既に`py`/`tex`/`plain`セッションが(エージェント無しで)起動中のときに`zj py claude`を
実行しても、既存セッションへ再接続するだけでagentタブは増えない。エージェント構成を
変えたいときは`zjdel [py|tex]`で一度落としてから`zj`系コマンドを引数付きで叩き直す。

## リポジトリ構成

```
wsl-wezterm-zellij/
├── .chezmoiignore              # 適用対象の切り替え
│                                  - Windows: wezterm設定のみ
│                                  - Linux共通: wezterm・README・setup系スクリプトは除外
│                                  - Linuxかつ非WSL(SSHサーバー): workspace/ も除外
├── dot_bashrc.tmpl               # → ~/.bashrc (zj / zjdel 関数。WSL/SSHで内容が変わるテンプレート。
│                                    WSL版のみ _zj_layout() でagentタブ付きレイアウトを動的生成)
├── dot_wezterm.lua               # → ~/.wezterm.lua (Windows側)
├── dot_config/
│   ├── nvim/                     # → ~/.config/nvim (LazyVim)
│   └── zellij/
│       ├── config.kdl.tmpl        # ホスト用(WSLのみclip.exe連携。SSHサーバーでは無し)
│       └── layouts/
│           └── plain.kdl           # コンテナなし・ホスト編集用レイアウト(WSL/SSH共通)
├── workspace/                    # WSLホストにのみ展開される(SSHサーバーでは丸ごと除外)
│   ├── Python-Work/
│   │   ├── Dockerfile         # Neovim/Zellij/uv 込みのPythonイメージ
│   │   ├── compose.yml        # サービス名: py。${HOME}:${HOME}でWSLホームをbind mount
│   │   │                        (agentタブがclaude/codexをホストと同じ認証で動かすため)
│   │   ├── dot_dockerignore   # → .dockerignore
│   │   └── zellij/            # コンテナに焼き込む設定(clip.exeなし)
│   │       ├── config.kdl
│   │       └── layouts/py.kdl
│   └── LaTeX-Work/
│       ├── Dockerfile         # Neovim/Zellij/texlive 込みのLaTeXイメージ
│       ├── compose.yml        # サービス名: tex
│       ├── dot_latexmkrc      # → .latexmkrc
│       └── zellij/
│           ├── config.kdl
│           └── layouts/tex.kdl
├── setup_wsl.sh               # WSLホスト側の非対話セットアップ
├── setup_ssh.sh               # 素のUbuntu(SSHサーバー)側の非対話セットアップ
└── setup_windows.ps1          # Windows側のセットアップ(WezTermなど)
```

`workspace/`以下はWSLホストで`chezmoi apply`した場合のみ`~/workspace/Python-Work`・
`~/workspace/LaTeX-Work`に展開される。`Dockerfile`や`compose.yml`をこのリポジトリで
管理しているので、セットアップスクリプト側でheredocを生成する必要がなくなっている。


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
ここまでで、WezTermを開くと自動でWSLが起動するように。\
`setup_windows.ps1`を使えば、この手順(+ chezmoiでの`.wezterm.lua`展開)は自動化されている。

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
これはホスト(WSL本体)側のNeovim/Zellijのセットアップで、`plain`レイアウト
(コンテナなしでさっと編集する用途)のために必要。Python-Work・LaTeX-Workで実際に
編集・実行するときのNeovim/Zellijは、後述のDockerコンテナの中に別途入っている。\
`setup_wsl.sh`を使えばこの手順は自動化されている。

### 4. workspace用意（ご自由に）
```
$ mkdir ~/workspace
$ cd ~/workspace
$ mkdir Python-Work
$ mkdir LaTeX-Work
```
`setup_wsl.sh`経由なら、`chezmoi apply`がこのディレクトリと`Dockerfile`/`compose.yml`を
自動的に作成する。

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
`Python-Work`ディレクトリ直下に`.venv/pyproject.toml/uv.lock/Dockerfile/compose.yml/.dockerignore`が置かれる構成です。\
`Dockerfile`/`compose.yml`/`.dockerignore`はこのリポジトリの`workspace/Python-Work/`が
ソースなので、手で書く必要はない。`pyproject.toml`/`uv.lock`だけは`uv init`/`uv add`で
プロジェクトごとに生成される(chezmoi管理外)。

### 7. コンテナの中で編集・実行する

`zj py`・`zj tex`を叩くと、`docker compose up -d`でコンテナを起こしたあと
`docker compose exec`でそのままコンテナの中に入り、コンテナ内にインストール済みの
Zellijが固定名のセッション(`py`/`tex`)にアタッチ(なければ作成)する。

| コマンド | どこで動く | セッション名 | レイアウト |
|---|---|---|---|
| `zj` | ホスト(WSL)のZellij + Neovim | `plain` | nvim + shell の2ペイン |
| `zj py` | Python-Work コンテナの中のZellij + Neovim(サービス名`py`) | `py` | work タブ = nvim+shell(bash)、monitor タブ = btop |
| `zj tex` | LaTeX-Work コンテナの中のZellij + Neovim(サービス名`tex`) | `tex` | 同上 |
| `zjdel [py\|tex]` | 対応するZellijサーバーで`kill-all-sessions -y`を実行 | - | - |

同じ`zj`系コマンドを何度実行しても、既存セッションがあればそれに再接続するだけ
(重複してセッションが増えることはない)。セッションを壊してしまったら
`zjdel`(または`zjdel py`/`zjdel tex`)→ 同じ`zj`系コマンドで、レイアウト通りの
まっさらな状態に作り直せる。

`zj [py|tex|] [claude|codex|both]`のように2つ目の引数を付けると、Claude Code /
Codexを動かすagentタブが追加される。詳しくは「アーキテクチャ」の
「エージェントタブ」を参照。

コンテナ内のNeovimはホストの`~/.config/nvim`をそのままbind mountして使うので、
LazyVimの設定は1箇所を編集するだけでホスト・コンテナ両方に反映される。
LSP/treesitter/pluginの実体(`~/.local/share/nvim`など)はDocker named volumeに
入るので、`docker compose build`でイメージを作り直してもプラグインの再インストールは
基本的に走らない。

### 8. Claude Code / Codexの導入(エージェントタブを使うなら)

`zj [py|tex|] [claude|codex|both]`のagentタブは、WSLホストの`~/.local/bin/claude`・
`~/.local/bin/codex`を(コンテナの場合はbind mount経由で)そのまま実行する仕組みなので、
**先にホスト側へ本体をインストール・ログインしておく必要がある**。`setup_wsl.sh`は
これを自動インストールしない(ログインがブラウザ経由の対話操作になるため)。

```
# Claude Code(公式インストーラ。~/.local/share/claude 配下に入り、
# ~/.local/bin/claude にシンボリックリンクが張られる)
$ curl -fsSL https://claude.ai/install.sh | bash

# Codex CLI(npm経由。Node/npmはsetup_wsl.shで導入済み)
$ npm install -g @openai/codex
```
(コマンド名やインストール手順は変わることがあるので、最新情報は各公式サイトも確認。)

インストール後、**一度ホスト側で直接**`claude`・`codex`を実行してログイン(ブラウザでの
OAuth認証など)を済ませておく。`~/.claude`・`~/.claude.json`・`~/.codex`に認証情報が
保存され、agentタブはこれをそのまま再利用するので、コンテナ内で再ログインする必要はない。
plainレイアウトのagentタブ(`zj claude`など)はホストで直接ログイン済みのものをそのまま
使うだけなので、追加設定は不要。

この手順を省いても`zj py`/`zj tex`/`zj`(エージェント無指定)は今まで通り使える。
agentタブを使おうとした時だけ、`claude: No such file or directory`のようなエラーになる。

### 9. SSHサーバー(WSLではない素のUbuntu)向けセットアップ

Docker無しで、Zellij + LazyVimの編集環境だけをリモートのUbuntuサーバーに入れたい場合。

```
$ bash setup_ssh.sh
```

`setup_wsl.sh`からDocker関連の手順(手順2・10相当)と`pdfview`まわり(手順8相当)を
丸ごと省いた版。やることは: 基本パッケージ → Rust/cargoでZellij → Neovim(tarball)
→ chezmoi(公式インストーラ、snap不要) → SSH鍵/GitHub認証 → `chezmoi init && chezmoi apply`
→ Neovimプラグイン同期、のみ。

`chezmoi apply`時に`env WSL_DISTRO_NAME`が立っていない(=WSLではない)と自動判定され、
`.wezterm.lua`・`workspace/`(Docker関連)は展開されず、`~/.bashrc`の`zj`/`zjdel`も
`plain`レイアウトだけを持つ版になる。セットアップ後は`zj`だけを使う(`zj py`/`zj tex`は
このホストには存在しない)。

### 既知の制約

- **クリップボード**: ホストのZellij設定(`copy_command "clip.exe"`)はWSL⇔Windowsの
  interopを使ってWindowsクリップボードにコピーする機能だが、コンテナの中や素のSSH
  サーバーからは`clip.exe`を呼べない。そのためコンテナ用・SSHサーバー用のZellij設定
  ではこの行を(テンプレートの条件分岐で)外してあり、コピーはWezTerm/ターミナル側の
  マウス選択などに頼る形になる。
- **PDFプレビュー(`<leader>v`)**: `~/.local/bin/pdfview`(SumatraPDF起動用)は
  WSLのinterop前提のスクリプトなので、ホスト側Neovim(`plain`レイアウト)からは
  動くが、コンテナ内Neovim(`zj tex`)やSSHサーバー上のNeovimからはそのままでは
  呼び出せない(`vim.fn.executable`でチェックして警告を出すだけに留めてある)。今後の課題。
