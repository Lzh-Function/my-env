# Python編: `zj py`での実践ワークフロー

`zj py`(Python-Workコンテナ)で実際にPythonを書く・動かす・テストする、具体的な状況別ガイド。
このリポジトリの`pyproject.toml`には`numpy`/`pandas`/`polars`/`scikit-learn`/`matplotlib`/
`seaborn`が最初から入っている。

## この環境で実際に動いているもの(検証済み)

- **LSP**: pyright(型チェック・補完・定義ジャンプ)。`gd`/`K`/`grn`などが効く
  ([`lazyvim.md`](./lazyvim.md)のLSP章参照)
- **フォーマッタ/リンタ**: **現状は何も設定されていない**(VSCode版Pythonでよくある
  「保存時に自動でBlack/ruffがかかる」は無い)。整形・静的解析をしたいなら後述の通り
  `ruff`をプロジェクトに追加して手動で実行する
- **デバッガ**: `nvim-dap`のようなビジュアルデバッガは入っていない。`print`文か
  `pdb`(後述)でデバッグする
- **パッケージ管理**: `uv`(pipやvenvを直接触らなくてよい高速ツール)

## 最初にこれだけ覚える

| したいこと | コマンド(shellペインで) |
|---|---|
| スクリプトを実行 | `uv run スクリプト.py` |
| パッケージを追加 | `uv add パッケージ名` |
| 開発用パッケージを追加(pytestなど) | `uv add --dev パッケージ名` |
| パッケージを削除 | `uv remove パッケージ名` |
| 入っているパッケージを見る | `uv pip list`(または`cat pyproject.toml`) |

**`python`コマンドを直接叩かないこと。** システムのPythonにはプロジェクトの依存関係が
入っていない。必ず`uv run ...`を使うか、`uv run`が自動で用意する`.venv`を経由する。

## シチュエーション別実例

### 「新しいスクリプトを書いて実行したい」

1. `zj py`でコンテナに入る(初回はイメージビルドが走る)
2. nvimペインで`<space>ff`または`:e sample.py`で新規ファイルを開く
3. コードを書いて`Esc` → `:w`で保存
4. `Alt+l`でshellペインに移動し、`uv run sample.py`で実行
5. `Alt+h`でnvimに戻って修正、を繰り返す

`uv run`は初回実行時に自動で`.venv`を作り、`pyproject.toml`に書かれた依存関係を
インストールしてから実行してくれる(pipやvenvのactivateを手で意識する必要はない)。

### 「numpy/pandasなどこの環境に無いパッケージを使いたい」

```
uv add requests
uv add --dev pytest ruff    # 開発時だけ使うツールは --dev を付ける
```

`uv add`すると`pyproject.toml`と`uv.lock`が自動更新される。実行時は変わらず
`uv run スクリプト.py`でよい。

### 「テストを書きたい」(VSCodeのTest Explorer相当)

```
uv add --dev pytest
```

```python
# test_sample.py
def add(a, b):
    return a + b

def test_add():
    assert add(2, 3) == 5
```

```
uv run pytest -v
```

VSCodeのTest Explorerのようなサイドバー統合UIは無いので、shellペインで`uv run pytest`を
叩いて結果を読む運用になる。特定のテストだけ実行したいときは
`uv run pytest test_sample.py::test_add`のようにノード指定ができる。

### 「型エラー・補完が効かない/おかしい」

- pyrightは**`pyproject.toml`が見える場所を開いたときだけ**アクティブになる
  (LSPのroot detection)。`/tmp`など無関係な場所に置いた`.py`ファイルでは効かない
- `<space>cl`(または`:LspInfo`)でpyrightがアタッチされているか確認
- 存在しないはずの警告が出続ける場合はNeovimを再起動(`:wqa` → `nvim`で開き直す)して
  pyrightのキャッシュをリセットする

### 「コードを整形したい/リンタをかけたい」(VSCodeの「保存時フォーマット」相当)

自動フォーマットは設定されていないので、`ruff`を追加して手動で実行するのが一番簡単。

```
uv add --dev ruff
uv run ruff format .     # 整形(Black相当)
uv run ruff check .      # リント(未使用importなど)
uv run ruff check --fix .  # 自動修正できるものは直す
```

保存のたびに自動でかけたい場合は、`~/.config/nvim/lua/plugins/`に`conform.nvim`の設定を
追加して`ruff_format`をpythonのフォーマッタとして登録する必要がある(この環境のデフォルトでは
未設定)。まずは手動実行から始めて、必要になったらこの設定に進むのがおすすめ。

### 「デバッグしたい」(VSCodeのブレークポイント相当)

ビジュアルなブレークポイントUIは無いので、コード中に`breakpoint()`を仕込んで
`pdb`(Python標準のデバッガ)を使う。

```python
def add(a, b):
    breakpoint()  # ここで実行が止まり、shellペインでpdbのプロンプトが使える
    return a + b
```

```
uv run sample.py
```

`(Pdb)`プロンプトで`n`(次の行)、`s`(関数の中に入る)、`p 変数名`(値を表示)、
`c`(続行)、`q`(終了)といった基本コマンドが使える。VSCodeほど視覚的ではないが、
実行を止めて変数の中身を見る、という目的は同じように達成できる。

### 「グラフ(matplotlib)を描いて確認したい」

コンテナにはディスプレイが無いので、`plt.show()`はそのままでは使えない。
**ファイルに保存してから、ホスト側(Windows)で開く**のが基本の流れ。

```python
import matplotlib
matplotlib.use("Agg")   # ディスプレイ無し環境向けのバックエンド
import matplotlib.pyplot as plt

plt.plot([1, 2, 3], [4, 5, 6])
plt.savefig("plot.png")
```

```
uv run plot_script.py
```

`plot.png`は`~/workspace/Python-Work/`(ホストとbind mountされているディレクトリ)に
そのまま生成される。確認方法:

- **簡単**: Windows Explorerで`\\wsl.localhost\Ubuntu\home\<ユーザー名>\workspace\Python-Work\`
  を開いてダブルクリック
- **ホスト側shellから**(`zj`のplainレイアウトで): `explorer.exe .`でカレントディレクトリを
  Windows Explorerで開く(コンテナ内の`zj py`からは`explorer.exe`を直接呼べないので、
  この操作はホスト側で行う。`<leader>v`のPDFプレビューが`zj tex`から使えないのと同じ理由。
  `../README.md`の既知の制約を参照)

### 「Jupyter Notebookのようにセル単位で試したい」

この環境にJupyter関連の拡張は入っていない。代わりに:

- 普通の`.py`ファイルに書いて`uv run スクリプト.py`で都度実行する
- どうしてもノートブック形式が欲しい場合は`uv add --dev jupyter`でJupyterLab自体を
  インストールし、`uv run jupyter lab --no-browser --ip=0.0.0.0`のようにサーバーとして
  立ち上げてブラウザ(Windows側)からアクセスする、という手もあるが、この環境の標準構成
  ではない(ポート転送など追加の設定が必要になる)

### 「新しいライブラリを試したいけど、プロジェクトを汚したくない」

`uv run --with パッケージ名 スクリプト.py`を使うと、`pyproject.toml`を変更せずに
一時的にそのパッケージが使える状態で実行できる。「ちょっと試したいだけ」のときに便利。

```
uv run --with httpx sample_using_httpx.py
```

## 困ったときの対処

### 「`uv run`が固まる/やたら遅い」

初回のパッケージダウンロード中の可能性が高い。`monitor`タブ(`Alt+o`)でネットワーク/CPU
負荷を確認。それでもおかしい場合は`zjdel py` → `zj py`でセッションをリセット。

### 「pyproject.tomlやuv.lockが壊れた気がする」

`uv.lock`は手で編集するものではない。`uv sync`(依存関係を`uv.lock`通りに再構築)や、
最終手段として`rm uv.lock && uv lock`でロックファイルを作り直せる。
