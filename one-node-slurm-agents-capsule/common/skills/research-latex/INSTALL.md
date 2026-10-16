# Installation & runtime prerequisites / 導入マニュアル

## A. 対象環境

推奨環境：Ubuntu / Debian (WSL2, Dev Container, Linux workstation)。**Python 3 + TeX Live + LuaLaTeX + LuaTeX-ja + Biber + latexmk + Poppler** を実行するコンテナ/マシンにインストールすること。Skill ファイルをどこに置いても、**TeX コマンドが実行される環境**にこれらの依存が必要です。

- GPU: 不要。
- root: OS依存ライブラリ導入時のみ必要。レポート生成は一般ユーザーで実行可能。
- ネット接続: OS導入時のみ必要。テンプレートのビルド自体はオフライン可。
- Python: run the standard-library CLI with `uv run --no-project python`; no project environment or additional packages are needed. Capsule images provide uv and infrastructure Python. Install uv first in other environments. Only optional figure regeneration needs `matplotlib`.
- CJKフォント: TeX Live の `HaranoAji` 日本語フォントを使う（OS配布のNoto CJKは必須でない）。
- TeXフォント: `fonts-lmodern` の Latin Modern OpenType を使う。

## B. Ubuntu / Debian の導入

TeX Live のパッケージ分割はOSリリースによって異なるため、以下は**比較的保守的な導入セット**です。容量に余裕を見込んでください。`texlive-full` は不要です。

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates \
  texlive-luatex texlive-lang-japanese \
  texlive-latex-recommended texlive-latex-extra \
  texlive-fonts-recommended texlive-pictures \
  texlive-science texlive-bibtex-extra \
  fonts-lmodern latexmk biber poppler-utils
```

このコマンドで `lualatex`, `kpsewhich`, LuaTeX-ja の `ltjsarticle`/`ltjsbook`, `biblatex`, `siunitx`, `tcolorbox` 等の本スキルで用いる機能を揃えることを意図しています。実際の利用環境で `doctor` / デモPDFビルドによって不足分を検証してください。

```bash
uv run --no-project python /path/to/research-latex/scripts/research_latex.py doctor
```

不足した `.sty` / `.cls` はOSの `apt-file search` / TeX Live package search 等で対応パッケージを調べ、環境のTeX Liveバージョンに合わせて追加します。異なる年のAPTパッケージと上流 `tlmgr` の混在は避けてください。

## C. Dev Container Dockerfile への追加例

既存の Dockerfile の `apt-get` セクションに次のRUNを追加できます。巨大なTeX Liveはコンテナイメージを増大させるため、頻繁に再ビルドする場合は共通ベースイメージに固定する方法も有効です。

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    texlive-luatex texlive-lang-japanese \
    texlive-latex-recommended texlive-latex-extra \
    texlive-fonts-recommended texlive-pictures \
    texlive-science texlive-bibtex-extra \
    fonts-lmodern latexmk biber poppler-utils \
    && rm -rf /var/lib/apt/lists/*
```

Skill はワークスペース内に `.agents/skills/research-latex/` (Codex) か `.claude/skills/research-latex/` (Claude Code) としてコピーしても、ホームディレクトリから読み込ませても構いません。Dev ContainerでそのSkillのディレクトリがマウントされ、エージェントに見えることを確認してください。

**重要**: WSL ホストにだけTeX Liveを導入しても、Dev Container内部から `lualatex` が実行できなければ使用できません。実際に `codex` / `claude` を走らせるコンテナで `doctor` を実行してください。

## D. インストール場所

ZIPを解凍すると、トップレベルに `research-latex/` が一つだけ現れます。

### Codex (repo-scoped)

```bash
mkdir -p .agents/skills
cp -a /path/to/research-latex .agents/skills/
```

### Claude Code (repo-scoped)

```bash
mkdir -p .claude/skills
cp -a /path/to/research-latex .claude/skills/
```

### Claude Code (user-scoped)

```bash
mkdir -p ~/.claude/skills
cp -a /path/to/research-latex ~/.claude/skills/
```

### Codex (user-scoped)

```bash
mkdir -p ~/.codex/skills
cp -a /path/to/research-latex ~/.codex/skills/
```

インストール先に既に同名ディレクトリがある場合、先に差分を確認してから更新してください。Codexの構成/配布チャネルによっては個人スキルの検索パスが異なることがあるため、認識しない場合は手元のCodexヘルプ/設定を確認してください。Agentの再起動・再読み込みが必要になる場合があります。

同じ作業リポジトリの `.agents/skills` と `.claude/skills` に両方配置しても問題ありません。共通ディレクトリに1回だけ実体を置き、そこへのリンクを両方に張って更新を一本化することもできます。

## E. 動作確認

```bash
SKILL_ROOT=/path/to/research-latex
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" doctor
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init --template technical --output ./sample-report
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build --project ./sample-report
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" validate --project ./sample-report
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" render --project ./sample-report --all --dpi 150
```

`sample-report/report.pdf` が生成され、`sample-report/build/rendered` に画像があれば必要な基本コンポーネントを確認できます。完成した画像は全ページを目視確認してください。

## F. 外部Pythonライブラリ（任意）

実データからプロットする場合、対象の `uv` プロジェクトに `matplotlib` / `pandas` 等を追加してください。スキルコアにはPython追加ライブラリは不要です。

```bash
uv add matplotlib
# または依存を恒久的に持たない単発実行
uv run --no-project --with matplotlib python /path/to/research-latex/scripts/plot_example.py input.csv output.pdf
```

コンテナ外や共有ログインノードで `pip install` する必要はありません。作図をCPUのローカル環境で行い、結果のPDFをLaTeXに読み込めます。

## G. 制限事項・セキュリティ

- **生成PDFの意味内容の正しさは自動保証されません。** `doctor` はインストール状態、`build` はコンパイル/構造検査、`render` は画像生成だけを扱います。
- 使用するLaTeX・Bib・外部データが未検証なら、TeXを実行する前に確認すること（TeXはデータだけでなくプログラマブルなマクロ処理系です）。スクリプトは `-shell-escape` を指定しません。
- 初回ビルドはLuaTeXのフォントキャッシュ構築のため時間がかかることがあります。メモリ・ディスク容量に余裕を確保してください。
- matplotlibで作ったデモ図はデフォルトの英字軸のみです。日本語をグラフに直接埋め込むなら、matplotlib側で日本語フォントを設定してください。
- 年号、著者、引用、ダミー図表はすべて実案件に合わせて修正してから外部配布してください。
