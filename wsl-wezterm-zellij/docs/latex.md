# LaTeX編: `zj tex`での執筆・コンパイル

`zj tex`(LaTeX-Workコンテナ)でのLaTeX執筆〜PDF確認〜エラー対処までの実践ガイド。
このコンテナはTeX Live全部入り(`texlive/texlive:latest`)なので、パッケージ不足で
コンパイルできない、という事態はほぼ起きない。

## この環境で実際に動いているもの(検証済み)

- **LSP**: `texlab`。コマンド名の補完、ラベル/参照(`\ref`/`\label`)の定義ジャンプなどが
  効く。ただし**ファイルを開いただけではコンパイルエラーは表示されない**(後述)
- **編集支援**: `vimtex`プラグイン。数式・環境(`\begin{}`〜`\end{}`)単位のテキスト
  操作や、コンパイル関連コマンド(`\l`から始まるキー)が使える
- **コンパイラ**: `latexmk`(lualatexエンジン、`.latexmkrc`で設定済み)。
  **`latexmk`自体はLaTeX-Workコンテナの中にしか無い**(ホストの`zj`からは実行できない)

## 最初にこれだけ覚える

| したいこと | 操作 |
|---|---|
| PDFにビルド(1回だけ) | shellペインで`latexmk -cd 文書名/main.tex` |
| 保存するたびに自動ビルド | shellペインで`latexmk -pvc -cd 文書名/main.tex` |
| ビルド成果物を掃除 | shellペインで`latexmk -c`(aux等)/`latexmk -C`(PDFも) |
| コンパイルエラーを見る | shellペインの出力、または`文書名/main.log`を直接開く |
| PDFを見る | ホスト側`zj`のnvimなら`<leader>v`。コンテナからは手動(後述) |

## シチュエーション別実例

### 「新しい文章を書いてPDFにしたい」(一番よくある流れ)

1. `zj tex`でコンテナに入る
2. nvimペインで`.tex`ファイルを開く/新規作成(`:e main.tex`)
3. 本文を書いて`Esc` → `:w`
4. `Alt+l`でshellペインに移動し、`latexmk -cd main.tex`を実行
5. エラーが無ければ`main.pdf`が生成される。実際のビルド出力はこんな感じになる:

```
Output written on main.pdf (1 page, 8169 bytes).
Transcript written on main.log.
Latexmk: All targets (main.pdf) are up-to-date
```

`Latexmk: All targets ... are up-to-date`が出ていれば成功。

### 「保存するたびに自動でビルドしてほしい」(VSCode拡張のオートビルド相当)

```
latexmk -pvc -cd main.tex
```

`-pvc`(preview continuously)を付けると、ファイルを保存するたびに自動で再ビルドされる
状態でシェルが張り付く(Ctrl+Cで止まるまで動き続ける)。書いては保存、を繰り返す執筆中は
これを1枚のペインで動かしっぱなしにしておくと便利。このリポジトリの`.latexmkrc`は
`README.md`のQuick Startで案内している`latexmk -pvc -cd <文書名>/main.tex`
(サブフォルダ運用)を前提にしている。

### 「コンパイルエラーが出た。何を見ればいい?」(VSCodeの赤い波線が無い代わりに)

**texlabはファイルを開いただけではエラーを教えてくれない**(inline diagnosticsは
実際のビルドを伴わないと出ない、と検証済み)。エラーの発見はビルド出力を読むところから
始まる。

実際のエラー例(存在しないコマンド`\undefinedcommand`を使った場合):

```
! Undefined control sequence.
l.3 Hello \undefinedcommand
                           {world}
...
Latexmk: Errors, so I did not complete making targets
Collected error summary (may duplicate other messages):
  lualatex: Command for 'lualatex' gave return code 1
      Refer to 'broken.log' and/or above output for details
```

読み方:

- `! ` で始まる行が実際のエラー内容。`Undefined control sequence`(未定義のコマンド)は
  典型的な「タイプミス」か「パッケージの`\usepackage`し忘れ」
- `l.3` は「3行目で発生」という意味。エディタでその行にジャンプして確認する
  (`:3`で3行目にジャンプできる)
- `Latexmk: Errors, so I did not complete making targets` が出たら、**古いPDFが
  そのまま残っている**(新しいPDFは生成されない)ので、直したつもりで確認したら
  実は直っていなかった、という事故に注意

### 「大量のログの中からエラー箇所だけ知りたい」

vimtexの`\le`(local leader `\` → `l` → `e`)でエラー一覧をquickfixウィンドウに
表示できる(直近のコンパイル結果から)。`]q`/`[q`でエラー間を移動できる
([`lazyvim.md`](./lazyvim.md)の「移動」章参照)。

### 「章・節をまたいで編集したい/目次を見たい」

| したいこと | キー |
|---|---|
| 目次(TOC)をサイドバー表示 | `\lt`(vimtex TOC) |
| 次/前のセクションに移動 | `]]` / `[[` |
| 数式環境ごとテキストオブジェクトとして操作 | `\begin{}`〜`\end{}`の中で`dae`(delete environment)など |
| コンパイル状況を確認 | `\lg` |
| コンパイルを止める | `\lk` |
| 生成物を掃除 | `\lc`(aux等) / `\lC`(PDFも含めて) |

これらはvimtex側の機能で、`latexmk`をシェルから直接呼ぶ方法と役割が重なる部分もある。
**このリポジトリでは「シェルで`latexmk -pvc`を張り付けておく」方式を基本としているので、
vimtexのコンパイル系コマンド(`\ll`など)は無理に使わなくてもよい。** 目次移動や
セクションジャンプなど「執筆中の移動・編集を楽にする」部分だけ使うのでも十分価値がある。

### 「複数ファイルに分割した大きな文書を書きたい」(`\input`/`\include`)

texlabは`\input{chapter1}`のようなファイル分割にも対応しており、`gd`で該当ファイルに
ジャンプできる。ビルドはメインファイル(`main.tex`など`\documentclass`がある方)に対して
`latexmk -cd main.tex`を実行すればよく、分割された`.tex`ファイル単体を直接ビルドする
必要はない。

### 「参考文献(BibTeX)を使いたい」

`.bib`ファイルを用意して`\bibliography{refs}`のように参照すれば、`latexmk`が
必要なツール(`bibtex`/`biber`)を自動判定して実行してくれる(TeX Live全部入りの
イメージなのでツール自体は揃っている)。texlabも`.bib`ファイルの中身を認識して
`\cite{}`の補完に使う。

### 「PDFを確認したい」

- **ホスト側の`zj`(plainレイアウト)からnvimを開いている場合のみ**、`<leader>v`で
  Windows側のSumatraPDFが自動起動する
- **`zj tex`(コンテナ内)からはこの自動起動は使えない**。生成された`main.pdf`は
  `~/workspace/LaTeX-Work/`配下(ホストとbind mount済み)にあるので:
  - Windows Explorerで`\\wsl.localhost\Ubuntu\home\<ユーザー名>\workspace\LaTeX-Work\...`
    を開いて直接見る
  - ホスト側shell(`zj`のplainレイアウトのshellペイン)から`explorer.exe .`で
    フォルダを開く

(この制約は[`docs/README.md`](../README.md)の既知の制約と同じ理由:
WindowsバイナリはWSL⇔コンテナのinterop越しには呼べない)

## 困ったときの対処

### 「ビルドが全く進まない/固まる」

`latexmk`(内部のlualatex)がエラー待ちで入力を求めて止まっている可能性がある。
`-interaction=nonstopmode`を付けて実行すると、確認を待たずにエラーとして処理を
進めてくれる。

```
latexmk -cd -interaction=nonstopmode main.tex
```

それでも反応が無ければ`monitor`タブ(`Alt+o`)でプロセスの状況を確認するか、
`zjdel tex` → `zj tex`でセッションごとリセットする。

### 「直したのに古いエラーのままPDFが変わらない」

一度失敗すると生成物が中途半端な状態で残ることがある。掃除してから再ビルドする。

```
latexmk -C -cd main.tex   # aux/log/PDFなど生成物を全部削除
latexmk -cd main.tex      # 最初から作り直す
```

### 「texlabの補完が効かない」

`<space>cl`(`:LspInfo`)でアタッチを確認。`.tex`ファイルとして開けているか
(拡張子や`filetype`)を確認する。

## Overleafと連携したい場合

複数人でOverleafの Web エディタと行き来しながら書きたい場合は
[`overleaf.md`](./overleaf.md)を参照。
