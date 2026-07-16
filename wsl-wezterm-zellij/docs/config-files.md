# 設定ファイル編: TOML・Dockerfile・dotfileを書く

`pyproject.toml`・`Dockerfile`/`compose.yml`・`~/.bashrc`のような「コードではないが
きちんと構文がある」ファイルを編集するときの話。`lazyvim.json`の`extras`に
`lang.toml`・`lang.docker`・`util.dot`が追加されており、それぞれ専用のLSP/lintが
最初から効く。

## この環境で実際に動いているもの(検証済み)

| 対象 | LSP | Lint | 備考 |
|---|---|---|---|
| `.toml`(`pyproject.toml`など) | `taplo` | - | 構文エラー・補完 |
| `Dockerfile`/`Containerfile` | `dockerls` | `hadolint` | ベストプラクティス指摘 |
| `compose.yml`/`docker-compose.yml` | `docker_compose_language_service` | - | |
| shellスクリプト・一部dotfile | `bashls` | `shellcheck`(拡張子や状況による) | 下記の制約に注意 |

## シチュエーション別実例

### 「`pyproject.toml`を編集していて構文ミスに気づきたい」

`taplo`が構文チェック・補完をしてくれる。`gd`のような定義ジャンプは無いが、
`<space>sd`(Diagnostics)で構文エラーがあれば表示される。VSCodeの「Even Better TOML」
拡張のシンプル版だと思えばよい。

### 「Dockerfileを書いていて、ベストプラクティス違反を指摘してほしい」(VSCodeのDocker拡張相当)

`hadolint`が自動でlintしてくれる。例えば:

```dockerfile
FROM ubuntu:24.04
RUN apt-get update
```

というだけの`Dockerfile`を開くと、`<space>sd`(Diagnostics)に

```
Delete the apt lists (/var/lib/apt/lists) after installing something
```

のような指摘が出る(`apt-get update`の後に`rm -rf /var/lib/apt/lists/*`で掃除して
いない、というよくある指摘)。このリポジトリの`workspace/*/Dockerfile`自体は
既にこの掃除をしている書き方になっている。

### 「`compose.yml`のインデントミスやキーの誤字に気づきたい」

`docker_compose_language_service`が`compose.yml`/`docker-compose.yml`に対して
構文チェック・補完を行う。`services:`配下のキー名の入力補完なども使える。

### 「このリポジトリ自体のDockerfile/compose.ymlを編集したい」

`zj`(ホスト、コンテナ不要)で`~/.local/share/chezmoi/wsl-wezterm-zellij/workspace/`
配下を開けばよい。編集後は`chezmoi apply`を忘れずに
(`../README.md`の「リポジトリ構成」参照)。

### 「`.bashrc`などdotfileを編集していてshellの構文ミスに気づきたい」

`util.dot`エクストラが`bashls`(shellスクリプト用LSP)と`shellcheck`(lint)を
有効にする。ただし2つ注意点がある:

1. **`bashls`は初期状態では`.git`ディレクトリが見つかる場所でしか有効にならない。**
   このリポジトリでは`~/.config/nvim/lua/plugins/dotfiles.lua`でこの制限を解除して
   あるので、`~/.bashrc`のようにホームディレクトリ直下にある単体のdotfileでも
   問題なくLSPが効く
2. **Neovim起動直後は最大20秒ほどLSPの起動を待つ必要がある。** Mason(ツール管理)側の
   初回チェックに時間がかかるため。すぐに`<space>cl`で確認しても「まだ何も
   アタッチしていない」ように見えることがあるが、故障ではないので少し待ってから
   再確認する

このリポジトリを`~/.local/share/chezmoi/`(gitリポジトリ)の中で編集する分には、
そもそも`.git`が見つかるので上記1の制約は最初から関係ない
(`dot_bashrc.tmpl`のようにchezmoiのソース側を編集する、普段の推奨ワークフロー)。

### 「今編集しているファイルがどの言語として認識されているか分からない」

`:set filetype?`(または`<space>cl`で開くLSP情報画面にも表示される)で確認できる。
`util.dot`は拡張子の無い設定ファイル(`kitty`の設定、`hyprland`の設定など)の
認識も広げているが、無関係なファイルまでは面倒を見ないので、変な言語判定に
なっていたら`:set filetype=sh`のように手動で上書きすることもできる。

## 困ったときの対処

### 「LSPがなかなか起動しない」

`util.dot`(特に`bashls`)は前述の通りMasonの初回チェックで最大20秒ほどかかることが
ある。`taplo`/`dockerls`/`docker_compose_language_service`はそれほど待たされない
(検証時は数秒以内にアタッチした)。焦らず`<space>cl`で数秒〜数十秒おきに確認する。

### 「新しいマシンでこれらの機能が効かない」

`~/.config/nvim/lazyvim.json`の`extras`に`lang.toml`/`lang.docker`/`util.dot`が
含まれているか確認。含まれていれば`chezmoi apply`後、初回だけ
`nvim --headless "+Lazy! sync" +qa`(または`:Lazy sync`)を走らせる必要がある場合がある。
