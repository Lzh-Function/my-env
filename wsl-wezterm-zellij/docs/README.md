# LazyVim × Zellij 実践マニュアル(VSCodeユーザー向け)

「ずっとVSCodeを使ってきた人」がこの環境(LazyVim + Zellij)で迷わず作業できるようになるための
マニュアル。キーバインド一覧だけでなく、**「こんな時どうする?」というシチュエーション別の実例**を
中心に構成している。

## 読む順番

1. **このページ**: VSCode用語 ↔ LazyVim/Zellij用語の対応表(まずここで頭を整理する)
2. [`zellij.md`](./zellij.md): Zellij(ターミナルマルチプレクサ)編。ウィンドウ・タブ・ペイン管理
3. [`lazyvim.md`](./lazyvim.md): LazyVim(エディタ)編。モード・移動・検索・LSP・Git
4. [`workflows.md`](./workflows.md): 両方を組み合わせた「この環境ならでは」の一連の作業例

急いでいるなら、まず`zellij.md`の「最初にこれだけ覚える」と`lazyvim.md`の「最初にこれだけ覚える」
だけ読んで、あとは困ったときにこのマニュアルを検索する使い方でも十分。

## 大前提: 2つのツールは役割がまったく違う

VSCodeは「エディタ」と「統合ターミナル」と「ウィンドウ管理」を1つのアプリが全部やってくれる。
この環境ではその3つが分かれている。

| 役割 | VSCode | この環境 |
|---|---|---|
| コードを書く | VSCode本体 | **Neovim(LazyVim)** |
| ターミナルを開く/並べる | 統合ターミナルパネル | **Zellij**(ペイン分割) |
| 複数の作業を並行する | ウィンドウ/ワークスペース切り替え | **Zellij**(タブ・セッション) |
| プロジェクトごとの実行環境 | Dev Containers拡張機能など | **Docker**(`zj py`/`zj tex`が自動でコンテナに接続) |

つまり「Zellijが外側の箱(ターミナルを何枚も並べる係)」「LazyVimがその箱の中の1枚で動く
エディタ」という二層構造。VSCodeの「1つのウィンドウに全部載っている」感覚とはここが一番違う。

## 用語対応表(VSCode → この環境)

迷ったらまずこの表に戻ってくること。

| VSCodeでの概念 | この環境での対応 | 備考 |
|---|---|---|
| エディタウィンドウ全体 | Zellij **セッション** | `zj`/`zj py`/`zj tex`ごとに別セッション |
| 上部のウィンドウタブ(複数プロジェクトを並べる) | Zellij **タブ**(画面上部のバー) | `work`/`monitor`/`agent`など |
| 画面分割(`Ctrl+\`) | Zellij **ペイン** | 1つのタブの中をさらに分割したもの |
| 統合ターミナル(`Ctrl+@`) | Zellij の **shellペイン** | nvimの隣に最初から用意されている |
| エディタタブ(開いているファイル1つ1つ) | Neovimの **バッファ** | ★最重要の勘違いポイント。下記参照 |
| コマンドパレット(`Ctrl+Shift+P`) | **which-key**(`<space>`を押して少し待つ) | LazyVimの心臓部。下記参照 |
| ファイルエクスプローラー | **Explorer (Snacks)**(`<space>e`) | |
| ファイルを名前で開く(`Ctrl+P`) | **Find Files**(`<space><space>` or `<space>ff`) | |
| 全体検索(`Ctrl+Shift+F`) | **Grep**(`<space>sg`) | |
| Source Control パネル | **Git Status**(`<space>gs`) | Snacksのgit連携 |
| 拡張機能パネル | `:Lazy`(プラグイン管理) / `:Mason`(LSP・ツール管理) | |
| settings.json | `~/.config/nvim/lua/config/options.lua` など | Luaで書く |
| ワークスペース切り替え | Zellij **タブ切り替え**、または`zj`/`zj py`/`zj tex`の使い分け | |
| 拡張機能によるDev Container | `zj py` / `zj tex`(Dockerコンテナに自動接続) | このリポジトリ独自の仕組み |

### ★最重要: 「タブ」という言葉が3種類の意味で衝突する

この環境で一番混乱しやすいポイント。**「タブ」という言葉が3つの異なるものを指す**:

1. **Zellijのタブ**(画面上部のバー。`work`/`monitor`/`agent`など) ── VSCodeの「ウィンドウを
   複数並べる」に近い
2. **Neovimのバッファ**(開いているファイル1つ1つ) ── VSCodeの「エディタタブ」に一番近いのは実は**これ**
3. **Neovim自身の`:tabnew`機能**(通称「Vimタブ」) ── LazyVimではほぼ使わない。存在は知っておくだけでよい

つまり「VSCodeで複数ファイルをタブで開き替える」動作は、LazyVimでは**バッファの切り替え**
(`<S-h>`/`<S-l>`または`<space>,`)で行う。Neovimの`:tabnew`(3番目)は使わなくてよい。
詳しくは[`lazyvim.md`](./lazyvim.md)の「バッファとウィンドウ」章を参照。

## この環境ならではの固有事情

- `zj` / `zj py` / `zj tex` / `zjdel` はこのリポジトリ独自のコマンド。標準のZellijコマンドではない
  (`../README.md`のQuick Start参照)
- `zj py claude` / `zj tex codex` / `zj py both` でClaude Code・Codexをagentタブとして起動できる
- Neovimの設定はホストとコンテナで共有されているので、`~/.config/nvim`をどちらで編集しても
  もう片方にすぐ反映される
