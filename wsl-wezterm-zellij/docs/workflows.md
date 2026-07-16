# この環境ならではの一連の作業例

Zellijの操作とLazyVimの操作を組み合わせた、実際の作業の流れを一気通貫で示す。
個別のキーバインドは[`zellij.md`](./zellij.md)・[`lazyvim.md`](./lazyvim.md)を参照。

## 1. Pythonで新しい関数を書いて動かすまで

VSCode + Dev Containers拡張機能でやっていたことの、この環境での対応版。

1. WezTermを開く(WSLに自動で入る)
2. `zj py`と打つ ── 初回はDockerコンテナが起動し、コンテナ内のZellijに接続される
   (2回目以降は同じセッションに繋ぎ直すだけなので一瞬)
3. `work`タブが表示される(左75%=nvim、右25%=shell)。何もなければ最初からここにいる
4. nvimペインで`<space>ff`(または`<space><space>`)でファイルを開く。新規作成なら
   `:e sample.py`のように`:e ファイル名`で新規ファイルを開ける
5. `i`で挿入モードに入り、コードを書く。書き終えたら`Esc` → `:w`で保存
6. `Alt+l`(または`Alt+右矢印`)でshellペインに移動
7. `python sample.py`のように実行して結果を確認
8. `Alt+h`でnvimペインに戻って続きを編集

途中でコンテナの負荷(pip install中など)を見たいときは`Alt+o`で`monitor`タブに移動して
`btop`を確認、`Alt+i`で`work`タブに戻る。

パッケージを追加したいときは、shellペインで`uv add パッケージ名`を実行する
(`../README.md`の「Python作業環境セットアップ」参照)。

## 2. LaTeXで新しい章を書いてPDFを確認するまで

1. `zj tex`でLaTeX-Workコンテナに接続
2. `work`タブのnvimペインで`.tex`ファイルを`<space>ff`で開く(またはshellペインから
   `nvim main.tex`)
3. 執筆(texlabのLSPが効くので、`gd`でラベル参照へのジャンプなどが使える)
4. shellペインで`latexmk -pvc -cd 文書名/main.tex`を実行してビルド
   (`.latexmkrc`で`-pvc`はファイル保存のたびに自動ビルドする設定)
5. PDFを確認する:
   - **ホスト側の`zj`(plainレイアウト)からnvimを開いている場合のみ**、`<leader>v`で
     Windows側のSumatraPDFが自動で開く
   - **`zj tex`(コンテナ内)からはこの機能は使えない**(`../README.md`の既知の制約参照)。
     生成された`main.pdf`をWindows Explorer(`\\wsl.localhost\...`経由)や
     `\mnt\c`配下のパスで直接開くか、SumatraPDFを手動で起動して確認する

## 3. コンテナ内でエラーが起きたときのトラブルシュート

### LSPの補完・定義ジャンプが効かない

1. `:LspInfo`で対象ファイルにLSPがアタッチされているか確認
2. `<space>cm`で`Mason`を開き、言語サーバー(pyright/texlabなど)がインストール済みか確認
3. それでも直らない場合はNeovim自体を再起動(`Esc` → `:wqa`で保存して終了 → `nvim`で開き直す)

### コンテナの調子がおかしい・処理が返ってこない

1. `monitor`タブ(`Alt+o`)で`btop`を見て、CPU/メモリが張り付いていないか確認
2. Zellijセッション自体をリセット: `zjdel py`(または`zjdel tex`)→ `zj py`で作り直す
3. それでも直らない場合はコンテナごと作り直す(ホスト側shellで):
   ```
   cd ~/workspace/Python-Work   # または LaTeX-Work
   docker compose down
   docker compose up -d
   ```

### 「セッションを壊してしまった」(タブを消しすぎた、レイアウトが崩れたなど)

これはエラーではなく想定内の操作。

```
zjdel py     # 対象のセッションを丸ごとリセット
zj py        # レイアウト通りに作り直す(nvimの中身=ファイルの変更は保存済みなら消えない)
```

`Ctrl+p` → `x`(ペインを閉じる)や`Ctrl+t` → `x`(タブを閉じる)を押しすぎて画面が
おかしくなっても、保存さえしていればコード自体は無事なので、遠慮なく`zjdel`していい。

## 4. Claude Code / Codexに実装を手伝ってもらいながら編集する

事前準備(初回のみ、ホスト側で): `../README.md`のTutorial「8. Claude Code / Codexの導入」を
参照し、`claude`/`codex`のインストールとログインを済ませておく。

```
zj py claude       # work・monitorに加えてagentタブ(3番目)でClaude Codeが起動
```

1. `Alt+o`を2回(または`Ctrl+t`→`3`)で`agent`タブに移動
2. Claude Codeにやってほしいことを指示する
3. `Alt+i`を2回で`work`タブに戻り、nvimでClaude Codeが編集したファイルの差分を確認
   (ファイルを開き直すか、`:e`で再読み込み。gitsigns系のキー`]h`/`[h`で変更行にジャンプできる)
4. 問題なければshellペインでテスト実行、コミット

`zj tex codex`のように`codex`を指定すればCodexに、`zj py both`なら同じagentタブの中で
上下split(上50%=claude、下50%=codex)で両方同時に動かせる。

**注意**: agentタブ付きのレイアウトは**セッション新規作成時にしか反映されない**。
すでに`zj py`(エージェント無し)でセッションが起動中のときに`zj py claude`を実行しても
agentタブは増えない。その場合は`zjdel py` → `zj py claude`でセッションを作り直す。

## 5. 複数プロジェクトを並行して進める

VSCodeで複数ウィンドウを開くのに近い操作。

- **PythonとLaTeXを同時に**: WezTermで新しいタブ(またはペイン)を開き、片方で`zj py`、
  もう片方で`zj tex`。セッションが完全に別なので干渉しない
- **同じプロジェクト内で別の作業**: 同じセッションの中で`Ctrl+t` → `n`で新しいタブを作る

## 6. ホストでちょっとした設定ファイルを見る/直す

Dockerコンテナを起こすほどでもない、`~/.bashrc`や`~/.config/nvim`自体を軽く見たいだけの
とき。

```
zj              # plainレイアウト。コンテナなしでホストのnvim+shellが起動
```

`<space>ff`で目的のファイルを開いて編集するだけ。このセッションだけホストの
`copy_command "clip.exe"`が有効なので、選択したテキストがWindows側のクリップボードにも
届く。

## 7. Gitでコミットするまでの一連の流れ

1. `<space>gs`(Git Status)で変更点を確認(VSCodeのSource Controlパネル相当)
2. 個別の差分は`<space>gd`(hunk単位)で確認
3. コミット自体はGUI相当の機能が薄いので、shellペイン(`Alt+l`)で素直に
   `git add`・`git commit`・`git push`を打つのが確実
4. pushしたあと、再度`<space>gs`で状態がきれいになったか確認

## 8. 新しいマシンでゼロから始めるとき

このマニュアル自体を読む前の話だが、位置づけとして記載しておく。

- Windows側のセットアップ: `../README.md`のTutorial 1〜2、または`setup_windows.ps1`
- WSL側のセットアップ: 同Tutorial 3〜7、または`setup_wsl.sh`
- SSHサーバー(Dockerなし)でこの環境だけ欲しい場合: Tutorial 9、`setup_ssh.sh`

セットアップが終わったら`zj`/`zj py`/`zj tex`のいずれかを打つところからが、この
マニュアルの出番になる。
