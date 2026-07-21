# WSL2-WezTerm-Zellij環境

> VSCodeからの乗り換えでLazyVim/Zellijの操作に迷ったら、[`docs/`](./docs/README.md)に
> シチュエーション別の実践マニュアル(日本語)がある。

## VScodeでよくね？
ただでさえwslの起動はメモリ食うのに、VScodeを被せて起動したときのリソース消費が激しい。スペックが足りないノートPCにおいてマルチタスクするためにも、軽量でありながらVScode-likeなターミナル環境を求めて採用。\
用途はPython-WorkとLaTeX-Workを想定。

## この環境のポイント

- **軽い**: WezTermはただのターミナルなので、VSCode(+WSL Remote)より圧倒的にメモリを食わない。GUIはWezTerm一枚、あとは全部ターミナルの中で完結する。
- **設定は全部chezmoiで一元管理**: `.bashrc`・Neovim(LazyVim)・Zellij・WezTerm・各プロジェクトの`Dockerfile`/`compose.yml`まで、このリポジトリ1つがソース。新しいPCでも下記のセットアップだけで同じ環境が復元できる。
- **編集・実行はコンテナの中で完結**: Python-Work・LaTeX-Workそれぞれ専用のDockerコンテナに、NeovimとZellijを直接インストールしてある。ホストのWSLを汚さず、プロジェクトごとに独立した言語ツールチェーン(uv/pyright、texlive/texlab)の上でLSPも含めて動く。
- **それでも「コンテナなしでさっと編集」もできる**: `zj`(引数なし)だけはホスト側のNeovim/Zellijで動く`plain`レイアウト。ちょっとした設定ファイルを見るだけなら、コンテナを起動する必要はない。
- **セッション名は固定・再接続前提**: `zj py`/`zj tex`は毎回タイムスタンプ付きの新規セッションを作るのではなく、`py`/`tex`という固定名のセッションに`attach --create`する。既にセッションが動いていればそれに繋ぎ直すだけ。
- **Zellijでタブ・ペイン管理、WezTermはタブバーなしの軽量フロントエンドに徹する**: 多重化はZellijに任せ、WezTerm側は`enable_tab_bar = false`・OpenGLフロントエンド・アニメ最小限で低スペック機でも軽快に。
- **同じリポジトリで素のSSHサーバー(Ubuntu)もサポート**: `dot_bashrc`・Zellij設定をchezmoiテンプレート化し、`env "WSL_DISTRO_NAME"`の有無でWSLホストか素のLinuxかを自動判定。Docker/`workspace`はWSL側にしか展開されず、SSHサーバー側は`zj`(plainレイアウト)だけのシンプルな構成になる。
- **Claude Code / Codexをagentタブとして統合(WSLホスト限定)**: `zj [py|tex|] [claude|codex|both]`で、レイアウトに専用タブを1枚追加してエージェントを起動できる。コンテナ側はWSLホストの`$HOME`をそのままbind mountして`HOME`環境変数を上書きするだけなので、コンテナ内に別途インストールし直したり再ログインしたりする必要がない(詳細は「アーキテクチャ」参照)。

## セットアップ

流れはどの対象でも同じ: **①このリポジトリをclone → ②chezmoi.tomlでsourceDirをこの
サブディレクトリ(`wsl-wezterm-zellij/`)に固定 → ③該当するsetupスクリプトを実行**。

このリポジトリ("my-env")は複数の環境プロファイルを将来的に共存させられるように、
chezmoiのsourceDirを明示的にサブディレクトリへ固定する構成になっている
(`chezmoi init`だけだとリポジトリ直下を丸ごとsourceとして扱おうとしてしまう)。

**前提**: このリポジトリはprivateなので、cloneする前にSSH鍵をGitHubに登録しておく
必要がある(具体的な手順は対象ごとに下記の各セクション内に記載)。

### Windows(WezTerm) ── WSLホストならここから始める

WSLホストとして使う場合は**必ずこちらを先に終わらせてから、下記「WSLホスト」に進む**。
理由: WSL側のセットアップにはこのリポジトリをWSLへcloneする必要があり、それには
動くSSH認証が要る。先にWindows側でSSH鍵を登録しておけば、WSL側はそれを間借りする
だけで済み、WSL側で別に鍵を作らずに済む(詳しくは「WSLホスト」の手順内で説明)。

**1. SSH鍵を登録**(このリポジトリはprivateなのでclone前に必要)

```powershell
ssh-keygen -t ed25519 -C "$env:USERNAME@$env:COMPUTERNAME"
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub
# 表示された公開鍵を GitHub → Settings → SSH and GPG keys → New SSH key に登録
```

**2. リポジトリをclone**

```powershell
winget install -e --id Git.Git   # git が無ければ

git clone git@github.com:Lzh-Function/my-env.git $env:USERPROFILE\.local\share\chezmoi
```

**3. `setup_windows.ps1`を実行**

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
& "$env:USERPROFILE\.local\share\chezmoi\wsl-wezterm-zellij\setup_windows.ps1"
```

`setup_windows.ps1`がwinget経由でWezTerm・SumatraPDF・chezmoi・Gitを導入し、続けて
フォント([Moralerspace](https://github.com/yuru7/moralerspace) Neon。日本語グリフ・
Nerd Fontアイコンとも標準搭載)をGitHub releaseから取得してユーザー単位でインストール
(管理者権限不要。winget未配布のためこのフォントだけは直接ダウンロードする方式)、
最後に`chezmoi init`(既にcloneされているので実質no-op)→`chezmoi apply`で
`.wezterm.lua`を展開する(`.chezmoiignore`によりWindows側はwezterm設定以外は無視される)。

WezTermだけ単体で使いたい(WSLホストのセットアップはしない)場合もここまでで完了。

### WSLホスト(Windows PC上のWSL2)

前提: 上記「Windows(WezTerm)」を先に終わらせていること。WSL2 + Ubuntuがまだなら:

```powershell
wsl --shutdown
wsl -l -v                    # ディストリビューションの確認
wsl --unregister Ubuntu      # 既存環境を消す場合のみ
wsl --install Ubuntu
```

WezTermを起動すると`default_domain = 'WSL:Ubuntu'`によりそのままWSLのシェルに入る。
**`setup_wsl.sh`を実行する前に**、WSL側の`ssh`をWindows純正の`ssh.exe`へ委譲する
シムを作っておく(直前にWindows側で登録したSSH鍵をそのまま使い回すため。WSL側で
別の鍵は作らない):

```bash
mkdir -p ~/.local/bin

cat > ~/.local/bin/ssh <<'EOF'
#!/bin/sh
exec /mnt/c/Windows/System32/OpenSSH/ssh.exe "$@"
EOF

chmod +x ~/.local/bin/ssh
```

(このシムはchezmoi管理には**しない**。`chezmoi apply`で配置される頃には既に
WSL側の最初のcloneが終わっているので、そこに置いても間に合わない。手で作る
1回きりの手順)

続けてリポジトリをclone・セットアップ:

```bash
sudo apt-get update && sudo apt-get install -y git   # git が無ければ

git clone git@github.com:Lzh-Function/my-env.git ~/.local/share/chezmoi
mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.toml <<'EOF'
sourceDir = "~/.local/share/chezmoi/wsl-wezterm-zellij"
EOF

bash ~/.local/share/chezmoi/wsl-wezterm-zellij/setup_wsl.sh
```

直前に作った`ssh`シム経由でGitHub認証は既に通っているので、`setup_wsl.sh`内の
SSH鍵チェックは素通りする(WSL側で新しい鍵が生成されることはない)。以降は非対話で:
基本パッケージ・Docker・Rust/Zellij・Neovim・lazygit・chezmoi本体(snap)の
インストールから`chezmoi apply`、Python/LaTeX両コンテナのビルドまで自動で行われる。
sudoパスワードの入力以外は操作不要。完了後は`source ~/.bashrc`してから`zj py`/`zj tex`
が使える(詳しくは下記「Quick Start」)。

Claude Code / Codexのagentタブを使いたい場合は、追加で「Claude Code / Codexの導入」
(下記)を行う。

### SSHサーバー(WSLではない素のUbuntu)

Docker無しで、Zellij + LazyVimの編集環境だけが欲しい場合。

**1. SSH鍵を登録**(このリポジトリはprivateなのでclone前に必要。登録済みなら不要)

```bash
ssh-keygen -t ed25519 -C "$(whoami)@$(hostname)"
cat ~/.ssh/id_ed25519.pub
# 表示された公開鍵を GitHub → Settings → SSH and GPG keys → New SSH key に登録
```

**2. リポジトリをclone → `setup_ssh.sh`を実行**

```bash
sudo apt-get update && sudo apt-get install -y git   # git が無ければ

git clone git@github.com:Lzh-Function/my-env.git ~/.local/share/chezmoi
mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.toml <<'EOF'
sourceDir = "~/.local/share/chezmoi/wsl-wezterm-zellij"
EOF

bash ~/.local/share/chezmoi/wsl-wezterm-zellij/setup_ssh.sh
```

`chezmoi apply`実行時に`env WSL_DISTRO_NAME`が立っていない(=WSLではない)と自動判定され、
Docker関連やWindows向けファイルは展開されず、`zj`(plainレイアウトのみ)が使える構成になる
(詳細は「アーキテクチャ」参照)。

**既存の`~/.bashrc`は上書きされない**: SSHサーバーは「まっさら」とは限らず、既に
手元で使っていたサーバーに後からこの環境を足すケースを想定している。`~/.bashrc`自体は
chezmoiの対象外にしてあり、`zj`/`zjdel`/`zjdoctor`本体は`~/.config/zj/zjrc.sh`
(常にchezmoi管理)に分離。`setup_ssh.sh`が`chezmoi apply`のあと、この`zjrc.sh`を
読み込む1行だけを`~/.bashrc`に**冪等に追記**する(既存の内容はそのまま、再実行しても
二重に追記されない)。WSLホスト側は今まで通り`~/.bashrc`ごとchezmoiが全体を管理する
(フルインストール前提のため)。

**sudoが使えないユーザーでもよい**: `setup_ssh.sh`はsudoが無くても止まらない。
Neovim/Rust/Zellij/chezmoi/lazygitはいずれも`~/.local`・`~/.cargo`配下に入るので
元々sudo不要。`sudo`が使えるかどうかを起動時に自動判定し、使えなければ
`apt-get install`はスキップして、代わりに何が足りないかだけを報告する:

- **無いと進められないもの**(`git`・`curl`)が本当に無ければそこで停止し、
  root権限のあるユーザーに`sudo apt-get install -y <pkg>`を頼むよう案内する
- **無くても致命的ではないが劣化するもの**(`ripgrep`・`fd-find`・`nodejs`・`npm`・
  `unzip`、および`cargo install zellij`に必要なCコンパイラ)は警告だけ出して続行する

root権限のあるユーザーに何を頼めばいいか事前に知りたい場合は、まず
`setup_ssh.sh`を(sudo無しユーザーで)一度実行してみれば、不足しているパッケージ名が
そのまま`sudo apt-get install -y ...`の形で表示される。

### Claude Code / Codexの導入(任意、agentタブを使うなら)

`zj [py|tex|] [claude|codex|both]`のagentタブは、WSLホストの`~/.local/bin/claude`・
`~/.local/bin/codex`を(コンテナの場合はbind mount経由で)そのまま実行する仕組みなので、
**先にホスト側へ本体をインストール・ログインしておく必要がある**。`setup_wsl.sh`は
これを自動化しない(ログインがブラウザ経由の対話操作になるため)。

```bash
# Claude Code(公式インストーラ)
curl -fsSL https://claude.ai/install.sh | bash

# Codex CLI(npm経由。Node/npmはsetup_wsl.shで導入済み)
npm install -g @openai/codex
```

インストール後、**一度ホスト側で直接**`claude`・`codex`を実行してログイン(ブラウザでの
OAuth認証など)を済ませておく。`~/.claude`・`~/.claude.json`・`~/.codex`に認証情報が
保存され、agentタブはこれをそのまま再利用するので、コンテナ内で再ログインする必要はない。

この手順を省いても`zj py`/`zj tex`/`zj`(エージェント無指定)は今まで通り使える。
agentタブを使おうとした時だけ、`claude: No such file or directory`のようなエラーになる。

## Quick Start

セットアップ済みならこれだけ:

```
zj          # ホスト側 Neovim + Zellij(plain: コンテナなしでさっと編集)
zj py       # Python-Work コンテナに入って編集・実行(nvim + shell、monitorタブにbtop)
zj tex      # LaTeX-Work コンテナに入って編集・実行(同上)

zj py claude    # ↑に加えてagentタブ(3番目)でClaude Codeを起動(要: 事前にclaude/codexを導入・ログイン)
zj tex codex    # ↑に加えてagentタブ(3番目)でCodexを起動
zj py both      # agentタブを上下split(上50%=claude、下50%=codex)
zj claude       # plainレイアウト + agentタブ(2番目)でホスト上のclaudeを起動

zjdel       # ホストの Zellij セッションをリセット
zjdel py    # Python-Work コンテナ内のセッションをリセット
zjdel tex   # LaTeX-Work コンテナ内のセッションをリセット

zjdoctor    # 環境ヘルスチェック(chezmoi diff・Lazy/Mason・Docker・コンテナ状態などを一括確認)
```

`zj`系はセッション名を固定(`plain`/`py`/`tex`)しているので、同じコマンドを打ち直すと
既存セッションに再接続する。何かを壊したら`zjdel [py|tex]` → `zj [py|tex]`で作り直せばOK
(常に`--layout`付きで作り直すので、壊れた状態が復元されることはない)。

素のUbuntu(SSHサーバー、WSLではない)にこのリポジトリを適用した場合は`zj`(`plain`レイアウト)
のみが使える。`zj py`/`zj tex`はDocker前提なのでそもそも定義されない。

`Python-Work`ディレクトリ直下は`.venv/pyproject.toml/uv.lock/Dockerfile/compose.yml/.dockerignore`
が置かれる構成。`Dockerfile`/`compose.yml`/`.dockerignore`はこのリポジトリの
`workspace/Python-Work/`がソースなので手で書く必要はなく、`pyproject.toml`/`uv.lock`だけは
`uv init`/`uv add`でプロジェクトごとに生成される(chezmoi管理外)。

`LaTeX-Work`は複数文書をサブフォルダで管理する想定(`~/workspace/LaTeX-Work/<文書名>/main.tex`)。
`latexmk -pvc -cd <文書名>/main.tex`のようにビルドする(詳しくは
[`docs/latex.md`](./docs/latex.md))。

コンテナ内のNeovimはホストの`~/.config/nvim`をそのままbind mountして使うので、
LazyVimの設定は1箇所を編集するだけでホスト・コンテナ両方に反映される。
LSP/treesitter/pluginの実体(`~/.local/share/nvim`など)はDocker named volumeに
入るので、`docker compose build`でイメージを作り直してもプラグインの再インストールは
基本的に走らない。

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
│                                  - Linux共通: wezterm・README・docs・setup系スクリプトは除外
│                                  - Linuxかつ非WSL(SSHサーバー): workspace/ と .bashrc 自体も除外
│                                    (既存の~/.bashrcを上書きしないため。下記zjrc.sh参照)
├── dot_bashrc.tmpl               # → ~/.bashrc (WSLのみchezmoiが全体を管理。中身は
│                                    ~/.config/zj/zjrc.sh を読み込む1行のみ)
├── dot_wezterm.lua               # → ~/.wezterm.lua (Windows側)
├── dot_config/
│   ├── nvim/                     # → ~/.config/nvim (LazyVim。lang.python/tex/markdown/toml/
│   │                                docker、util.dotのextrasを有効化)
│   ├── zj/
│   │   └── zjrc.sh.tmpl           # → ~/.config/zj/zjrc.sh (zj/zjdel/zjdoctor本体。WSL/SSHで
│   │                                 内容が変わるテンプレート。WSL版のみ_zj_layout()で
│   │                                 agentタブ付きレイアウトを動的生成。WSL/SSHどちらでも
│   │                                 chezmoiが常にフル管理 ── ユーザーの既存ファイルではないため)
│   └── zellij/
│       ├── config.kdl.tmpl        # ホスト用(WSLのみclip.exe連携。SSHサーバーでは無し)
│       └── layouts/
│           └── plain.kdl           # コンテナなし・ホスト編集用レイアウト(WSL/SSH共通)
├── workspace/                    # WSLホストにのみ展開される(SSHサーバーでは丸ごと除外)
│   ├── Python-Work/
│   │   ├── Dockerfile         # Neovim/Zellij/uv/lazygit 込みのPythonイメージ
│   │   ├── compose.yml        # サービス名: py。${HOME}:${HOME}でWSLホームをbind mount
│   │   │                        (agentタブがclaude/codexをホストと同じ認証で動かすため)
│   │   ├── dot_dockerignore   # → .dockerignore
│   │   └── zellij/            # コンテナに焼き込む設定(clip.exeなし)
│   │       ├── config.kdl
│   │       └── layouts/py.kdl
│   └── LaTeX-Work/
│       ├── Dockerfile         # Neovim/Zellij/texlive/lazygit 込みのLaTeXイメージ
│       ├── compose.yml        # サービス名: tex
│       ├── dot_latexmkrc      # → .latexmkrc
│       └── zellij/
│           ├── config.kdl
│           └── layouts/tex.kdl
├── docs/                      # VSCodeユーザー向け実践マニュアル(chezmoi管理外)
├── setup_wsl.sh               # WSLホスト側の非対話セットアップ
├── setup_ssh.sh               # 素のUbuntu(SSHサーバー)側の非対話セットアップ
└── setup_windows.ps1          # Windows側のセットアップ(WezTermなど)
```

`workspace/`以下はWSLホストで`chezmoi apply`した場合のみ`~/workspace/Python-Work`・
`~/workspace/LaTeX-Work`に展開される。`Dockerfile`や`compose.yml`をこのリポジトリで
管理しているので、セットアップスクリプト側でheredocを生成する必要がなくなっている。

## 既知の制約

- **クリップボード**: ホストのZellij設定(`copy_command "clip.exe"`)はWSL⇔Windowsの
  interopを使ってWindowsクリップボードにコピーする機能だが、コンテナの中や素のSSH
  サーバーからは`clip.exe`を呼べない。そのためコンテナ用・SSHサーバー用のZellij設定
  ではこの行を(テンプレートの条件分岐で)外してあり、コピーはWezTerm/ターミナル側の
  マウス選択などに頼る形になる。Neovim自身がマウスを捕捉する(`mouse=a`)ため、
  素のドラッグ選択ではなくShift+ドラッグでターミナル側の選択に切り替える必要がある
  (詳しくは[`docs/editing.md`](./docs/editing.md))。
- **PDFプレビュー(`<leader>v`)**: `~/.local/bin/pdfview`(SumatraPDF起動用)は
  WSLのinterop前提のスクリプトなので、ホスト側Neovim(`plain`レイアウト)からは
  動くが、コンテナ内Neovim(`zj tex`)やSSHサーバー上のNeovimからはそのままでは
  呼び出せない(`vim.fn.executable`でチェックして警告を出すだけに留めてある)。今後の課題。
