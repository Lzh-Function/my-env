# research-latex — Scientific LaTeX Report Skill

**Codex / Claude Code compatible.** 日本語・英語の研究レポートをLuaLaTeXで組版し、参考文献、図表、再コンパイル、PDFの構造検証とページ画像化まで扱うAgent Skillです。

> **重要**: 同梱されたレポートの数値、学習曲線、研究条件はすべて人工的なデモデータです。実測結果として引用・配布しないでください。SMILES文献は実在しますが、実際の成果物では必要な場合のみ引用してください。

## できること

| テンプレート | コマンド | 特徴 |
|---|---|---|
| Academic paper | `academic` | A4 2段組。論文草稿や研究短報を想定 |
| Technical report | `technical` | A4 1段組。実験記録、詳細評価レポート向け |
| Scientific monograph | `monograph` | 章立て、定義、式、目次、文献リストを備えた教科書風 |

### ファイル構成

```text
research-latex/
├── SKILL.md                         # Agent Skill の本体
├── README.md                        # この説明書
├── INSTALL.md                       # Linux/Dev Container 導入手順
├── assets/
│   ├── common/preamble.tex          # 日本語/英語の共通組版設定
│   ├── templates/
│   │   ├── academic/main.tex        # 2段組
│   │   ├── technical/main.tex       # 1段組
│   │   └── monograph/main.tex       # 書籍型
│   └── examples/                    # 架空のCSV, Bib, ベクター図
├── scripts/
│   ├── research_latex.py            # doctor/init/build/validate/render
│   ├── plot_example.py              # optional matplotlib 例示グラフ生成
│   └── {doctor,build,validate,render}.sh
├── references/                      # 執筆・組版・QAガイドライン
└── examples/previews/               # 検証済みデモPDF 3種類
```

### クイックスタート

以下で `SKILL_ROOT` はこのファイルのディレクトリを指します。Skill が導入済みの環境で実行してください。

```bash
export SKILL_ROOT="$HOME/.claude/skills/research-latex"   # 自分の設置先に変更
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" doctor
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init \
    --template technical --output ./reports/my-experiment
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build \
    --project ./reports/my-experiment
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" render \
    --project ./reports/my-experiment --all --dpi 150
```

出力プロジェクト：

```text
reports/my-experiment/
├── main.tex                 # 編集対象
├── preamble.tex             # プリアンブル
├── references.bib           # 参考文献
├── figures/example-curve.pdf
├── data/example-metrics.csv
├── scripts/plot_example.py
├── build/                   # 中間ファイルとPDF検査用PNG
└── report.pdf               # 最終出力
```

自分で編集するときは `main.tex` と `references.bib` をまず差し替えます。プロジェクトはスキルから独立しており、後からSKILL本体を更新しても過去のレポートは組版可能です。

### 全テンプレートを動作検証

```bash
for name in academic technical monograph; do
    uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init \
        --template "$name" --output "./reports/demo-$name"
    uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build \
        --project "./reports/demo-$name"
done
```

### 画像を自分のデータから作り直す

次はオプションの `matplotlib` が必要です。

```bash
uv run --no-project --with matplotlib python \
  ./reports/my-experiment/scripts/plot_example.py \
  ./reports/my-experiment/data/example-metrics.csv \
  ./reports/my-experiment/figures/example-curve.pdf
```

**利用時の指示例**：

> research-latexを使って今回の学習ダイナミクスの評価をtechnicalレポートにまとめ、架空データは必ず削除して。実験値は指定したmetrics.csvから算出し、作図コードと図の生成元を残す。report.pdfの全ページを画像で点検してから返して。

### 設置範囲

- Codex: プロジェクトの `.agents/skills/research-latex/`、または個人スキル用ディレクトリ（環境により `~/.codex/skills/`）。
- Claude Code: プロジェクトの `.claude/skills/research-latex/`、または `~/.claude/skills/research-latex/`。
- **両者から同じスキルを使う**なら、共有配置 `~/agent-skills/research-latex` に置いて両方のskillsディレクトリからシンボリックリンクを張る運用も可能です。コンテナ間・別マシン間では、それぞれの実行環境内でパスが見える必要があります。

詳細は [INSTALL.md](INSTALL.md) を参照してください。

### 品質保証の限界

`build` はTeXコンパイルとPDF構造/テキストの検証、`render` はPDFページのPNG化を行います。**視覚的検査そのものはスクリプトではなくエージェント/人間が画像を見て行います**。PDF出力成功をもって図表配置や研究内容の正確性を保証するわけではありません。
