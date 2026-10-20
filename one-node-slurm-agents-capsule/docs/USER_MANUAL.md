# agentrun 利用マニュアル

`agentrun` は、Claude Code と Codex を Slurm の計算ノード上の Apptainer コンテナで動かすためのコマンドです。対話しながらの作業、バッチ実行、会話の再開、会話履歴の保存、両エージェントによる相互監査に対応しています。エージェントを省略すると Claude Code を使います。

本書では、`agentrun` を実行してジョブを投入するマシンを**投入元ホスト**、ジョブが実際に動くマシンを**計算ノード**と呼びます。また、起動から終了までの一回の作業を**実行**と呼び、その記録を保存する `.agent-runs/<run_id>/` を**実行ディレクトリ**と呼びます。

通常の作業は計算ノード上のコンテナで行います。投入元ホストでは、起動の準備、認証、終了後の会話履歴の保存などを行います。

## 目次

- [初回セットアップ](#初回セットアップ)
  - [コマンドの登録](#コマンドの登録)
  - [コンテナイメージのビルド（初回必須）](#コンテナイメージのビルド初回必須)
  - [認証情報の登録と最初の実行](#認証情報の登録と最初の実行)
- [実行前の確認](#実行前の確認)
  - [エージェントの一覧](#エージェントの一覧)
  - [設定ファイルの検証](#設定ファイルの検証)
  - [実行環境の診断](#実行環境の診断)
  - [実行計画の確認](#実行計画の確認)
- [実行方法](#実行方法)
  - [対話しながら作業する](#対話しながら作業する)
  - [バッチで実行する](#バッチで実行する)
  - [目標ファイルの作成と指定](#目標ファイルの作成と指定)
  - [実験・継続作業・レビューの実行](#実験継続作業レビューの実行)
  - [ウィザードで起動する](#ウィザードで起動する)
  - [セッションの再開と入力補完](#セッションの再開と入力補完)
- [作業領域と出力](#作業領域と出力)
  - [基本概念](#基本概念)
  - [投入場所と作業対象の指定](#投入場所と作業対象の指定)
  - [実行ディレクトリの構成](#実行ディレクトリの構成)
  - [状態・ログ・成果物の確認](#状態ログ成果物の確認)
- [会話履歴の保存](#会話履歴の保存)
  - [保存のタイミング](#保存のタイミング)
  - [保存先と実行場所の記録](#保存先と実行場所の記録)
  - [保存する会話と出力](#保存する会話と出力)
  - [保存上の制限](#保存上の制限)
  - [手動保存と回収の再開](#手動保存と回収の再開)
  - [SQLite に保存した会話の検索](#sqlite-に保存した会話の検索)
- [対話による相互監査](#対話による相互監査)
  - [監査の依頼と質疑応答](#監査の依頼と質疑応答)
  - [修正・反論後の再監査](#修正反論後の再監査)
  - [対象ファイルと制限](#対象ファイルと制限)
  - [中止・追加ラウンド・一括実行](#中止追加ラウンド一括実行)
  - [設定と保存先](#設定と保存先)
  - [相互監査の検証](#相互監査の検証)
- [Rust と日本語 LaTeX](#rust-と日本語-latex)
- [外部サービスの認証情報](#外部サービスの認証情報)
  - [秘密情報を環境変数で渡す（任意）](#秘密情報を環境変数で渡す任意)
  - [GitHub 操作の仲介サービス（任意）](#github-操作の仲介サービス任意)
- [設定の管理](#設定の管理)
  - [エージェントごとの設定](#エージェントごとの設定)
  - [共通の指示の変更](#共通の指示の変更)
  - [スキルの管理](#スキルの管理)
  - [フックの管理](#フックの管理)
- [コマンドの登録と削除](#コマンドの登録と削除)
- [実装範囲と終了処理](#実装範囲と終了処理)
  - [現在の実装範囲](#現在の実装範囲)
  - [実行時の保護と終了処理](#実行時の保護と終了処理)
- [基本動作のテスト](#基本動作のテスト)
  - [Dockerによる疑似クラスタの検査](#dockerによる疑似クラスタの検査)
  - [実クラスタでの基本動作の確認](#実クラスタでの基本動作の確認)
- [問題が起きたとき](#問題が起きたとき)
  - [`agentrun` が見つからない](#agentrun-が見つからない)
  - [`doctor` で認証の確認が失敗する](#doctor-で認証の確認が失敗する)
  - [トークンの期限切れ・認証エラーが出る](#トークンの期限切れ認証エラーが出る)
  - [コンテナ内での Apptainer 実行が失敗する](#コンテナ内での-apptainer-実行が失敗する)
  - [`dry-run` に表示されたディレクトリが存在しない](#dry-run-に表示されたディレクトリが存在しない)
  - [`status` が `{}` のまま](#status-が--のまま)
  - [`verify-run` が `artifacts/report.md` で失敗する](#verify-run-が-artifactsreportmd-で失敗する)
  - [Codex の信頼設定を保存できない](#codex-の信頼設定を保存できない)
  - [フックが動かない](#フックが動かない)
- [コマンド一覧](#コマンド一覧)
  - [主なオプション](#主なオプション)

<a id="quick-start"></a>

## 初回セットアップ

### コマンドの登録

このマニュアルを含むリポジトリのルートで、次のコマンドを実行します。

```bash
./install.sh          # 変更内容の確認のみ
./install.sh --apply  # コマンドと Bash 補完を登録
```

`install.sh --apply` は `$HOME/.local/bin/agentrun` にシンボリックリンクを作成します。`$HOME/.local/bin` を `PATH` に含めておけば、以後は作業したいディレクトリから `agentrun` を実行できます。

<a id="image-ビルド初回必須"></a>

### コンテナイメージのビルド（初回必須）

コンテナイメージの `.sif` は Git で管理していないため、初回は計算ノードでビルドします。`runtime/apptainer/base-system.sif` がないと、`doctor` の確認で `[FAIL]` になり、エージェントを起動できません。

```bash
runtime/apptainer/build-images.sh  # 実行する内容の確認のみ
srun --partition <partition> runtime/apptainer/build-images.sh --run

# 既存イメージを強制的に作り直す場合
srun --partition <partition> runtime/apptainer/build-images.sh --run --force
```

ビルドするイメージは `base-system.sif` の一つです。エージェントの CLI は各ジョブの起動時に公式インストーラから最新版を導入するため、CLI の更新だけならイメージの再ビルドは不要です。

`--force` を省略すると、イメージがない場合や、既存のイメージが定義ファイル `base-system.def` より新しくない場合にビルドします。既存イメージのほうが新しければ、`reusing existing ...` と表示して再利用します。内容ではなく更新日時による判定なので、確実に作り直したい場合は `--force` を指定してください。

実際のビルドには Slurm のジョブ割り当てが必要です。`SLURM_JOB_ID` が設定されていない環境では `--run` によるビルドを拒否します。確認だけなら投入元ホストでも実行できます。

`--run --force` でのビルドに成功すると、旧構成の `base-agent.sif` が残っていれば削除します。ビルドに失敗した場合や確認だけの場合は削除しません。

ビルド完了後、以下で状態を確認します。

```bash
agentrun agents
agentrun validate
agentrun doctor --agent <name>   # 使用するエージェントを指定する（例: claude, codex）
```

`doctor` の `image:base-system.sif` が `[OK]` になればイメージの準備は完了です。

<a id="認証情報のセットアップ初回必須"></a>

### 認証情報の登録と最初の実行

`agentrun` は各エージェントの認証情報を `$HOME/.agentrun/auth/<agent>/`（認証ストア）に管理します。

初回は **`auth login` を使う方法を推奨します**。投入元ホストでのログインと、認証ストアへの登録を一括で行います。

```bash
agentrun auth login --agent claude
agentrun auth login --agent codex
agentrun auth status
```

両方のエージェントをまとめてログイン・登録する場合:

```bash
agentrun auth login --all
agentrun auth status
```

`auth login` を使うには、対象の CLI（`claude` / `codex`）を投入元ホストにインストールし、`PATH` から呼び出せるようにしてください。インストール先の例は `$HOME/.local/bin/` です。

**既にホスト側でログイン済みの場合** は `auth import` のみ実行します。

```bash
agentrun auth import --agent claude
agentrun auth status --agent claude
```

`auth import` がコピーするファイルは以下の通りです。

```text
claude      $HOME/.claude/.credentials.json
            $HOME/.claude.json
codex       $HOME/.codex/auth.json
```

以後のジョブは、認証ストアから認証情報を実行ごとの一時ホームへコピーします。認証ストアにない場合だけ、投入元ホストの元ファイルを参照します。

認証ストアをリセットして再インポートする場合:

```bash
agentrun auth reset --agent codex
agentrun auth login --agent codex
```

Codex を対話式に起動する例:

```bash
agentrun dry-run assist --agent codex --partition <partition> --show-mounts
agentrun assist --agent codex --partition <partition>
```

TTY が不要なバッチ実行にする場合:

```bash
agentrun assist --submit --agent codex --partition <partition> "作業内容を説明してください"
```

`<partition>` は利用環境の Slurm パーティション名に置き換えてください。毎回 `--partition` を書きたくない場合は、環境変数 `AGENTRUN_SLURM_PARTITION` に設定できます。

```bash
export AGENTRUN_SLURM_PARTITION=<partition>
agentrun assist --agent codex
```

`AGENTRUN_SLURM_PARTITION` も `--partition` も指定しない場合、`agentrun` はパーティション指定を Slurm に渡しません。その場合はクラスタ側の既定のパーティションを使います。

実行時間の上限は、実行プロファイルごとに既定値が決まっています。

```text
assist        01:00:00
review        01:00:00
multi-review  02:00:00
experiment    08:00:00
campaign      08:00:00
smoke-test    00:10:00
```

時間を変える場合は `--time HH:MM:SS` を指定します。

```bash
agentrun assist --agent codex --partition <partition> --time 02:00:00
```

## 実行前の確認

<a id="agent-一覧"></a>

### エージェントの一覧

```bash
agentrun agents
```

利用可能なエージェント CLI を表示します。対応するエージェントは `codex` と `claude` で、省略時は `claude`（Claude Code）を使います。

`--agent`、`--reviewers`、`--agents` はこの2種類だけを受け付けます。未対応の名前はエラーになります。ウィザードに保存されたエージェントが未対応なら `claude` に戻し、未対応の名前を含む保存済み監査担当・エージェントの一覧は空に戻します。

例:

```text
Available agents:
  codex        available /home/li/.local/bin/codex
  claude       available /home/li/.local/bin/claude
```

<a id="validate"></a>

### 設定ファイルの検証

```bash
agentrun validate
```

以下を検証します。

- 必須ファイルの存在
- JSON / TOML の形
- フックスクリプトの実行権限
- エージェント別シンボリックリンク
- フック定義ファイルと生成済み設定の一致
- `common/hooks/*.py` が各エージェントの定義ファイルで分類済みであること

`validate` がフックの不一致を報告した場合は、該当エージェントの `sync-*` を実行してから再度 `validate` します。

```bash
agentrun sync-claude
agentrun sync-codex
agentrun validate
```

<a id="doctor"></a>

### 実行環境の診断

```bash
agentrun doctor --agent claude   # 使用するエージェントを指定する
agentrun doctor --all            # 両エージェントの認証を検証する
```

以下を確認します。

- Slurm コマンド: `sinfo`, `squeue`, `srun`, `sbatch`
- `jq`
- エージェント CLI
- 認証ファイル
- イメージ: `runtime/apptainer/base-system.sif`
- FUSE 前提条件: ホストの `/dev/fuse` と、イメージ内の `libfuse3` / `liblzo2`
- 秘密情報のファイル: 存在、アクセス権限（600 か）、設定済みの変数名、現在のディレクトリ配下に無いか
- GitHub CLI 仲介サービス: `secrets/gh.env` の `GH_TOKEN` とアクセス権限、`secrets/.env` に `GH_TOKEN` が書かれていないか
- `.agent-runs` の書き込み可否
- Git リポジトリ / ブランチ / 未コミットの変更

FUSE のチェックは常に WARN 止まりで、実行を FAIL にはしません。コンテナ内でさらに `apptainer exec` を使う場合の確認項目だからです。使う場合は `--allow-fuse` の指定と、[問題が起きたとき](#troubleshooting)を参照してください。

秘密情報の環境変数と GitHub CLI 仲介サービスのチェックも WARN 止まりです。どちらも任意のためです。

ログインノード上で `apptainer` や `uv` が見つからない場合は WARN です。計算ノードやイメージ内で提供される構成もあるため、WARN は即失敗とは限りません。

**`--all` を指定すると両エージェントの認証を検証します。** 使用しないエージェントの認証ファイルが未設定の場合、そのエージェントの認証チェックが `[FAIL]` になります。使用するエージェントだけを確認する場合は `--agent NAME` を使ってください。

認証ファイルは次の場所を確認します。認証ストアになければ、投入元ホストの元ファイルを参照します。

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
```

認証ストアにもホストにも存在しない場合のみ `[FAIL]` になります。認証ストアには `agentrun auth import --agent NAME` でインポートしてください。

<a id="dry-run"></a>

### 実行計画の確認

```bash
agentrun dry-run assist --agent codex --partition <partition> --show-mounts
```

`dry-run` はエージェントを起動せず、以下を表示します。

- 実行 ID
- 実行プロファイル
- エージェント
- リポジトリパス
- 投入元ホストに作成する予定の実行ディレクトリ
- 起動方法
- Slurm の起動コマンド、または `sbatch` に渡す引数
- Apptainer コマンド
- バインドマウント
- プロンプト
- 必要な成果物

`dry-run` は `.agent-runs/<run_id>/` を作成しません。表示される `host_run_directory` は予定パスです。

## 実行方法

<a id="assist"></a>

### 対話しながら作業する

対話式で起動する例:

```bash
agentrun assist --agent codex --partition <partition> --repo .
```

起動時の作業指示（`PROMPT`）は不要です。エージェントは「ユーザーの指示に従ってください」という最小限の初期コンテキストで起動し、その後はユーザーがインタラクティブに指示を与えます。`PROMPT` を指定した場合は無視され、警告が表示されます。

挙動:

- `srun --pty` を使う
- 実行ディレクトリを作成する
- 認証を実行ごとのホームディレクトリに一時配置する
- Apptainer 内で対話式エージェント CLI を起動する（初期プロンプトは最小システムコンテキストのみ）
- 終了時に `<run_dir>/home/` を削除する

TTY が必要です。TTY のない環境では `assist --submit` を使います。

`--repo` は省略可能です。省略時は現在のディレクトリが `/workspace` にマウントされます。

<a id="assist-submit"></a>

### バッチで実行する

```bash
agentrun assist --submit --agent codex --partition <partition> --repo . "実行してほしい作業の指示"
```

挙動:

- `.agent-runs/<run_id>/` を作成する
- `submit.sbatch` を生成する
- 認証を実行ごとのホームディレクトリに一時配置する
- `sbatch` で投入する
- ジョブ終了時に `<run_dir>/home/` を削除する
- `live/status.json` に `success` / `failed` を書く

エージェントが必須成果物を作らない場合、Slurm ジョブが成功しても `verify-run` は失敗することがあります。特に `artifacts/report.md` は、空でないことを検証します。

<a id="goal-ファイル"></a>

### 目標ファイルの作成と指定

`--goal` に渡す `goal.yaml` は、エージェントに与える目標の構造化定義です。

#### テンプレートの生成

```bash
agentrun init-goal
```

現在のディレクトリに `goal.yaml` を生成します。`goal.yaml` が既に存在する場合はエラーになります。テンプレートの実体は `templates/goal.yaml` です。

生成されたファイルの主なフィールド:

```yaml
project: my-project          # 実行の識別名
mode: experiment             # assist / experiment / campaign / レビュー / multi-review
goal:
  objective: |               # エージェントへの目標説明（自由記述）
    ...
  success_criteria:          # 達成条件リスト（エージェントが参照する）
    - ...
budgets:
  walltime: "01:00:00"
  cpu_cores: 2
  memory: 8G
  max_trials: 1
  max_disk_gb: 10
outputs:
  required:                  # verify-run が期待するパス
    - artifacts/report.md
    - artifacts/metrics.json
    - live/command_log.jsonl
```

`agentrun` は `goal.yaml` の内容を検証しません。フィールドはエージェントが参照する情報であり、`outputs.required` に書いた一覧だけで `verify-run` の検証対象を変更できるわけではありません。現在は、agentrun が定めた必須ファイル一覧を使って検証します。

#### --goal の使い方

`--goal` を指定すると、`goal.yaml` がコンテナ内の `/runs/goal.yaml` としてアクセスできます。エージェントはプロンプト内の `Goal file: /runs/goal.yaml` という記述を手がかりとしてファイルを読み込みます。

```bash
agentrun init-goal
# goal.yaml を編集してから投入
agentrun experiment --submit --agent codex --partition <partition> --goal goal.yaml "目標ファイルに従って作業してください"
```

<a id="experiment--campaign--review--multi-review"></a>

### 実験・継続作業・レビューの実行

これらは、実行プロファイルごとに目標と必要な成果物を定めたバッチ実行です。一回の投入で起動する作業エージェントは一つです。

```bash
agentrun experiment --submit --agent codex --partition <partition> --goal tests/fixtures/goal_smoke.yaml --repo . "目標ファイルに従って作業してください"
agentrun campaign --submit --agent codex --partition <partition> --goal path/to/goal.yaml --repo . "目標に沿って継続的に実験してください"
agentrun review --submit --agent claude --partition <partition> --target-diff path/to/diff.patch --repo . "この差分をレビューしてください"
agentrun multi-review --submit --agent codex --partition <partition> --agents claude,codex --repo . "レビュー結果を整理してください"
```

重要:

- `--submit` を省略すると準備だけを行い、ジョブは投入しません。
- `review` / `multi-review` は名前上レビュー用ですが、現状は 1 エージェントだけを起動します。
- `--agents` の一覧はプロンプトに追記するだけです。
- 複数エージェントを自動起動して比較・集約する機能は未実装です。

すべての実行プロファイルで、次のファイルが必要です。パスは `/runs` からの相対パスです。

```text
live/status.json           live/heartbeat.txt
live/stdout.log            live/stderr.log
live/command_log.jsonl     live/events.jsonl
live/current_task.md
artifacts/report.md        artifacts/git_diff.patch
artifacts/metrics.json     artifacts/run_title.txt
```

`artifacts/report.md` と `artifacts/run_title.txt` は空にできません。作業名は、英小文字で約 5 語の一行にまとめます。バッチ実行用のプロンプト、実行プロファイル、共通ルール、`agentrun-contract` スキルは、いずれもこの出力要件に合わせています。`verify-run` は、これらの成果物に加えて実行情報とジョブの終了記録も確認します。

実行プロファイルごとの追加ファイルは次のとおりです。

```text
assist        追加ファイルなし
experiment    artifacts/proposed_next.yaml
campaign      artifacts/proposed_next.yaml, artifacts/proposed_train.sbatch
review        reviews/review_findings.json
multi-review  reviews/{claude,codex}.md, reviews/summary.md,
              reviews/disagreements.json, reviews/final_recommendation.md
```

<a id="wizard-mode"></a>

### ウィザードで起動する

`agentrun wizard` は、起動方法や計算資源をメニューで選ぶためのウィザードです。最後に、同じ条件で実行する CLI コマンドも表示します。起動処理は通常の `agentrun` と共通です。

```bash
agentrun wizard
```

入力と出力の両方に端末（TTY）が必要です。端末を使えない環境では、質問を始めずにエラーで終了します。

画面表示には、利用可能なツールを次の順で使います。

1. `gum`
2. `whiptail` または `dialog`
3. Bash の `read` / `select`

次のツールへ切り替えるときは、理由を標準エラー出力へ一行表示します。インストール方法は表示しません。

#### 起動までの流れ

1. 実行モードとエージェントを選びます。
2. 起動方法を選びます。`assist` は対話実行かバッチ投入、それ以外はその場でバッチ投入するか準備だけにするかを選びます。
3. 作業リポジトリ、パーティション、GPU 数、メモリ、CPU 数、制限時間を指定します。
4. 追加マウント、FUSE の使用、秘密情報の環境変数、GitHub 操作の仲介を設定します。秘密情報と仲介の質問は、設定がある場合だけ表示します。
5. 目標ファイルと作業指示を指定します。レビュー用のモードでは、対象ファイルや担当の一覧も指定します。
6. 設定の要約と CLI コマンドを確認します。最後の起動確認で Yes を選ぶと実行し、No を選ぶと起動せずに終了します。

#### 入力と取り消し

入力欄には既定値が入り、そのまま編集できます。Enter で採用し、値を消すと空欄になります。Bash の標準入力を使う場合も同じです。

「← 戻る」または `:back` で前の項目へ戻れます。Ctrl+C、Esc、Cancel ボタン、Ctrl+D、`:cancel` はウィザード全体の中止です。何も起動せず、終了コード 130 で終了します。`whiptail` は Ctrl+C のキー入力を受け付けないため、Esc か Cancel ボタンを使ってください。

入力値は、その場で検証します。不正な場合は入力を残して修正を求めます。

| 項目 | 入力条件 |
| --- | --- |
| 作業リポジトリ | 存在するディレクトリ。`~` と相対パスは絶対パスへ展開します。Git リポジトリでなければ注意を表示します。 |
| GPU 数 | 0 以上の整数。選んだパーティションに `sinfo` 上の GPU がなければ注意を表示します。 |
| メモリ | 数値と、任意の `K` / `M` / `G` / `T`。例: `16000M`、`64G` |
| CPU 数 | 1 以上の整数 |
| 制限時間 | Slurm の時間形式。例: `HH:MM:SS`、`MM`、`D-HH:MM:SS` |
| 目標ファイル | 空欄、または存在するファイル |
| 作業指示 | 対話式の `assist` 以外では必須 |

追加マウントは、`--bind` と同じ `SRC:DST[:ro|rw]` の形式で入力します。複数指定する場合は、スペースかカンマで区切ります。

| パス | 内容 |
| --- | --- |
| `~/data:/data:ro` | /path/to/work:/extra:rw |

`SRC` は投入元ホストに存在する必要があります。`DST` を省略すると `SRC` と同じパスを使います。指定する `DST` は絶対パスにします。権限は `ro` または `rw` を指定します。`none` を入力すると追加マウントをすべて解除します。コピーしたコマンドに含まれる `--bind` / `-B` は無視して値だけを読み取ります。

一行入力した後、追加確認の "Add more?" で Yes を選ぶと続きの入力ができます。入力を分けたいときに使ってください。`gum` の入力欄には文字数制限を設けていません。

<a id="partition-の選択"></a>

#### パーティションの選択

`sinfo` が使える場合は、一覧からパーティションを選びます。各項目には、`sinfo` が報告する GPU 情報も表示します。表示例は `gpu (GPU: gpu:a100:4)` や `cpu (no GPU)` です。

クラスタの既定値を使う項目と、名前を直接入力する "Type a partition name..." も選べます。一覧にない名前を入力すると、そのまま使うか確認します。`sinfo` が使えない環境では名前を直接入力し、空欄ならクラスタの既定値を使います。

#### 前回の値の再利用

起動した実行の回答は `~/.agentrun/wizard-last` に保存し、次回の既定値に使います。

- モード、エージェント、起動方法、パーティション、GPU 数、追加マウント、FUSE、秘密情報・仲介サービスの有無、`multi-review` のエージェント一覧は、前回の値を使います。
- メモリ、CPU 数、制限時間は、前回と同じモードを選んだ場合だけ使います。
- リポジトリ、目標ファイル、作業指示、レビュー対象は、前回と同じディレクトリで起動した場合だけ使います。別のプロジェクトで前回の作業対象を引き継ぐことを防ぐためです。
- `agentrun wizard --agent claude` のように指定した値は、保存済みの値より優先します。質問は省略せず、既定値として表示します。
- 中止した場合や、起動確認で No を選んだ場合は保存しません。

#### 表示される CLI コマンド

"Same run without the wizard:" の後に表示するコマンドは、コピーして同じ条件で実行できます。既定値と同じメモリ・CPU 数・制限時間、GPU 数 0、現在のディレクトリを使う `--repo` など、省略しても条件が変わらない引数は表示しません。

<a id="wizard-の戻るパス補完再開"></a>

### セッションの再開と入力補完

ウィザードの各ステップで「← 戻る」または `:back` を使うと前の入力へ戻れます。`:cancel`、Esc、Ctrl+C はキャンセルです。バインドのホスト側パスは Tab で補完できます。
CLI の Bash 補完は `install.sh --apply` で登録されます。現在のシェルでは `source runtime/agentrun/agentrun.bash` で有効にできます（`--bind` のマウント元、`--repo`、`--goal`）。

```bash
agentrun resume --list
agentrun resume RUN_ID --preview
agentrun resume RUN_ID --time 02:00:00 --mem 16000M --cpus 4
agentrun resume  # 対話的に選択
```

ウィザードのモードでも `resume` を選べます。会話データは `.agent-runs/.sessions` に保存し、元のログを残して新しい実行で再開します。保存前の旧実行は再開対象になりません。
起動時のインストーラログは `live/agent_install.log`、インストールした CLI の情報は `artifacts/agent-cli.json` に保存します。計算ノードから公式インストーラに接続できる必要があります。

## 作業領域と出力

### 基本概念

`agentrun` は、エージェントごとに CLI、設定、認証、フックを切り替えます。実行ディレクトリの作成、Slurm スクリプトや Apptainer 起動コマンドの生成、状態・ログ・成果物の確認は共通の処理です。

共通のコンテナ内パス:

| パス | 内容 |
| --- | --- |
| `/home/sandbox` | コンテナのホーム |
| `/workspace` | 作業対象のリポジトリ |
| `/runs` | 実行記録と成果物 |
| `/scratch` | 実行ごとの一時作業領域 |
| `/node-scratch` | 計算ノードの SSD（存在する場合のみ） |
| `/cache` | 実行ごとのキャッシュ |
| `/home/sandbox/ai-agent-config/common/hooks` | 共通フック（読み取り専用） |
| `/home/sandbox/ai-agent-config/common/skills` | 共通スキル（読み取り専用） |

設定リポジトリからは、共通スキル、共通ルール、エージェント別の設定、起動用の補助プログラムなど、必要なものを個別に渡します。ただし、この設定リポジトリ自体を `--repo` や追加マウントで指定した場合は、その範囲もコンテナから見えます。

ホスト側の実行ディレクトリ:

```text
.agent-runs/<run_id>/
```

`dry-run` は `host_run_directory` を表示しますが、実際のディレクトリは作成しません。副作用なしで実行計画を確認するためのコマンドです。

`assist` は例外的に `--submit` なしで対話式実行します。`experiment` / `campaign` / `review` / `multi-review` は `--submit` なしでは起動に必要なファイルを準備するだけで、ジョブは投入しません。

<a id="任意ディレクトリで実行した場合の挙動"></a>

### 投入場所と作業対象の指定

`agentrun` は、コマンドを実行した投入元ホストの現在のディレクトリを基準に実行ディレクトリを作ります。`--repo` を省略した場合は、その現在のディレクトリ自体がコンテナ内の `/workspace` に読み書き可能な状態でマウントされます。

例えばホスト側で `/path/to/my-project` にいる状態で以下を実行した場合:

```bash
cd /path/to/my-project
agentrun assist --agent codex --partition <partition>
```

主な対応関係は以下です。

```text
ホスト: /path/to/my-project                         -> コンテナ: /workspace:rw
ホスト: /path/to/my-project/.agent-runs/<run_id>    -> コンテナ: /runs:rw
ホスト: /path/to/my-project/.agent-runs/<run_id>/home    -> コンテナ: /home/sandbox
ホスト: /path/to/my-project/.agent-runs/<run_id>/scratch -> コンテナ: /scratch:rw
ホスト: /path/to/my-project/.agent-runs/<run_id>/cache   -> コンテナ: /cache:rw
計算ノード: /scratch/<submission-user>          -> コンテナ: /node-scratch:rw（存在する場合のみ）
ホスト: <ai-agent-env repository>/common/hooks      -> コンテナ: /home/sandbox/ai-agent-config/common/hooks:ro
ホスト: <ai-agent-env repository>/common/skills     -> コンテナ: /home/sandbox/ai-agent-config/common/skills:ro
```

`--repo` を指定した場合、`/workspace` にマウントされる対象だけが変わります。実行ディレクトリは引き続き `agentrun` を実行したディレクトリの `.agent-runs/<run_id>/` に作られます。

計算ノードの SSD 領域は **`/node-scratch`** で利用します。投入元ホストで `id -un` から取得したユーザー名を固定し、`srun` / `sbatch` で計算ノードに入った後、`/scratch/<ユーザー名>` がディレクトリとして存在する場合だけ自動で読み書き可能にマウントします。投入元ホストからこのパスが見える必要はありません。通常起動・再開・バッチ起動に共通の動作です。

マウントされるとコンテナ内の `AGENTRUN_NODE_SCRATCH=/node-scratch` が設定されます。存在しない場合は空文字になり、SSD のマウントを省略して通常どおり起動します。ディレクトリの自動作成や終了時の削除はしません。同じユーザーが同じノードで動かす実行からは同じ内容が見えるため、必要に応じて作業ごとのサブディレクトリを作成してください。別ノードからは同じ内容が見えるとは限らず、投入元への自動コピーや履歴保存にも含まれないので、残す成果物は `/runs/artifacts` へコピーしてください。

既存の `/scratch` は引き続き実行ディレクトリ内の `scratch/` を指します。`/node-scratch` は別のマウントであり、既存の一時ファイルやキャッシュの配置は変わりません。この追加のためのイメージ再ビルドは不要です。

```bash
cd /path/to/run-ledger
agentrun assist --agent codex --partition <partition> --repo /path/to/my-project
```

この場合:

```text
ホスト: /path/to/my-project                         -> コンテナ: /workspace:rw
ホスト: /path/to/run-ledger/.agent-runs/<run_id>    -> コンテナ: /runs:rw
```

エージェントは全て `/workspace` に移動してから起動します。したがって、エージェントの作業ディレクトリは `/workspace` です。Codex では CLI 側にも `--cd /workspace` を渡します。

<a id="run-directory"></a>

### 実行ディレクトリの構成

`dry-run` を除く実行は `.agent-runs/<run_id>/` を作成します。

主な構成:

| パス | 内容 |
| --- | --- |
| `.agent-runs/<run_id>/home/` | 認証情報と設定を一時配置するホーム |
| `.agent-runs/<run_id>/container_config/` | 実行専用の設定コピー |
| `.agent-runs/<run_id>/prompt.txt` | エージェントに渡す初期プロンプト |
| `.agent-runs/<run_id>/goal.yaml` | 目標の定義 |
| `.agent-runs/<run_id>/apptainer_exec.sh` | コンテナの起動コマンド |
| `.agent-runs/<run_id>/submit.sbatch` | Slurm に投入するスクリプト |
| `.agent-runs/<run_id>/live/` | 実行状態、ログ、生存確認、コマンド履歴 |
| `.agent-runs/<run_id>/artifacts/` | 報告書、変更差分、評価指標 |
| `.agent-runs/<run_id>/reviews/` | レビューの成果物 |

`.agent-runs/<run_id>/` 直下の主なファイル:

| パス | 内容 |
| --- | --- |
| `capsule.yaml` | 実行 ID、モード、エージェント、リポジトリ、目標などの実行情報 |
| `prompt.txt` | 初期プロンプト。対話式の assist では最小限の環境説明のみ |
| `goal.yaml` | `--goal` で指定した目標ファイルのコピー。未指定ならモードとエージェントだけを記録 |
| `apptainer_exec.sh` | コンテナを起動するコマンド |
| `submit.sbatch` | `sbatch` 用スクリプト。`--submit` 時に投入する |

`live/` は実行中状態とログの置き場です。

| パス | 内容 |
| --- | --- |
| `live/status.json` | 実行状態。初期値は `{}` |
| `live/heartbeat.txt` | 最後に生存確認を書き込んだ時刻 |
| `live/current_task.md` | 現在の作業内容。初期値は `initialized` |
| `live/stdout.log` | エージェントの標準出力用。バッチ実行では空のまま残る場合がある |
| `live/stderr.log` | コンテナ起動スクリプトの標準エラー出力 |
| `live/slurm.out` | Slurm の標準出力。投入したジョブの出力は主にここで確認する |
| `live/slurm.err` | Slurm の標準エラー出力 |
| `live/command_log.jsonl` | ツール名とコマンド文字列の履歴。出力本文は含めない。空でも異常とは限らない |
| `live/events.jsonl` | 実行イベントの履歴。空でも異常とは限らない |
| `live/exit_code.txt` | ジョブ内で実行したコマンドの終了コード |
| `live/slurm_job_id.txt` | Slurm のジョブ ID。準備だけの場合は空のことがある |

`artifacts/` はエージェントが最終成果物を書く場所です。

| パス | 内容 |
| --- | --- |
| `artifacts/report.md` | 最終報告書。`verify-run` では空でないことを確認する |
| `artifacts/git_diff.patch` | エージェントが作った変更差分。変更がなければ空 |
| `artifacts/metrics.json` | 評価指標と結果の要約。初期値は `{}` |
| `artifacts/run_title.txt` | 必須の作業名。空にせず、英小文字で約 5 語の一行にする |
| `artifacts/environment.txt` | 投入したジョブの環境情報。記録を許可した項目のみ |
| `artifacts/container.txt` | Apptainer のバージョンなどのコンテナ情報 |
| `artifacts/data_manifest.txt` | 入出力データの一覧。未使用なら空 |
| `artifacts/proposed_next.yaml` | experiment / campaign での次の作業の提案 |
| `artifacts/proposed_train.sbatch` | campaign での学習ジョブの提案 |

`reviews/` はレビュー系実行プロファイルの出力置き場です。

| パス | 内容 |
| --- | --- |
| `reviews/review_findings.json` | review の指摘を構造化した結果。初期値は `{}` |
| `reviews/claude.md` | Claude によるレビューの記入先 |
| `reviews/codex.md` | Codex によるレビューの記入先 |
| `reviews/summary.md` | レビューの要約 |
| `reviews/disagreements.json` | エージェント間で意見が異なる点。初期値は `{}` |
| `reviews/final_recommendation.md` | 最終的な提案 |

`home/` はコンテナの `/home/sandbox` です。認証ファイルや書き込み可能設定はここに一時配置されます。`submit.sbatch` には終了時の後片付け処理があり、ジョブ終了時に `<run_dir>/home/` は削除されます。

`scratch/` と `cache/` は実行ごとに独立したディレクトリで、それぞれ `/scratch` と `/cache` にマウントします。内容は実行ディレクトリ内に残り、削除するまで保持されます。同じ計算ノードであっても、別の実行には自動で引き継がれません。

`/node-scratch` は計算ノードの `/scratch/<投入元ユーザー名>` を条件付きでマウントする別の領域です。実行ディレクトリの一部ではなく、履歴保存や終了時の一時ホームの削除の対象にも含まれません。

初期作成直後や準備のみの実行では、空ファイル、`{}`、`initialized` だけのファイルが多く残ります。これは異常ではありません。`--submit` したジョブが進むにつれて `live/` と `artifacts/` が更新されます。

#### 認証ストアの仕組み

エージェント認証ファイルは `$HOME/.agentrun/auth/<agent>/`（認証ストア）から `<run_dir>/home/` に一時配置され、コンテナには `/home/sandbox` として渡されます。ホスト `$HOME` の認証ファイルを直接読み書き可能な状態でマウントする構成ではありません。認証ストアにファイルがない場合だけ、投入元ホストの `$HOME` にある元ファイルを参照します。

一時配置対象の認証ファイル:

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
```

各エージェント CLI は、更新用トークン（`refresh_token`）が利用できれば、ジョブ実行中に期限切れになったアクセストークンを自動更新します。更新できない場合や認証が失われた場合は、再ログインして認証ストアを更新します。

```bash
agentrun auth login --agent NAME
```

`.agent-runs/latest` は最後に準備した実行を指します。未完了実行や準備のみの実行を指す場合があります。

<a id="run-確認"></a>

### 状態・ログ・成果物の確認

```bash
agentrun status
agentrun logs
agentrun logs --follow
agentrun tail
agentrun list-runs
agentrun open-run .agent-runs/latest
agentrun verify-run .agent-runs/latest
```

挙動:

- `status`: `.agent-runs/latest/live/status.json` を表示
- `logs`: `.agent-runs/latest/live/stdout.log` を表示
- `logs --follow`: 標準出力ログを `tail -f`
- `tail`: `logs --follow` と同等
- `list-runs`: `.agent-runs/` 直下の実行を列挙
- `open-run`: シンボリックリンクを解決した実行パスを表示
- `verify-run`: 必須ファイル、JSON / JSONL の形式、終了状態を検証

`latest` が未完了実行を指している場合、`status` が `{}` のまま正常終了したり、`verify-run` が失敗したりします。これは検出として正常です。

<a id="conversation-archives"></a>

## 会話履歴の保存

会話履歴は、`agentrun` を実行した投入元ホストで Markdown と SQLite に保存します。変換にはシステム Python の標準ライブラリを使います。モデルの呼び出し、追加の Python パッケージ、イメージの再ビルドは不要です。

### 保存のタイミング

| 実行方法 | 終了時の処理 |
| --- | --- |
| 対話式の `assist` / `resume` | `srun` が戻った後、投入元ホストでセッションの終了を記録し、会話履歴を保存してから一時ホームを削除します。 |
| `--submit` によるバッチ実行 | 計算ノード側でセッションの終了を記録し、一時ホームを削除します。投入元ホストの回収プロセスがジョブの終了を待ち、永続化済みの履歴を保存します。ジョブの投入コマンド自体は、終了を待たずに戻ります。 |

回収プロセスは、5 秒ごとに `squeue` で状態を確認します。終了済みのジョブ ID が `squeue` に拒否された場合は、`sacct` でも確認します。照会に失敗しただけでは終了と判定しません。

実行ディレクトリ名に作業の要約が追加されても、元の実行 ID を使って追跡します。また、実行ごとのロックにより回収プロセスの重複起動を防ぎます。

### 保存先と実行場所の記録

全プロジェクトの履歴を、投入元ホストの `~/.agentrun/history/` に集約します。

| パス | 内容 |
| --- | --- |
| `.agent-runs/<run>/live/history_export.json` | 保存状態、ホスト名、保存先、警告 |
| `.agent-runs/<run>/live/history_export.log` | 対話実行の保存処理の診断ログ |
| `.agent-runs/<run>/live/session_finished.txt` | バッチ実行の終了処理完了を示すファイル |
| `~/.agentrun/history/runs/<archive_id>/conversation.md` | 閲覧用の Markdown |
| `~/.agentrun/history/runs/<archive_id>/metadata.json` | 実行情報と元の会話履歴の情報 |
| `~/.agentrun/history/index.sqlite3` | 全プロジェクト共通の会話データベース |
| `~/.agentrun/history/jobs/<archive_id>.json` | バッチのジョブ ID、投入元、回収状態 |
| `~/.agentrun/history/jobs/<archive_id>.log` | バッチ履歴の回収ログ |

保存先を変える場合は、起動前に次を設定してください。手動保存や回収の再開時にも同じ設定を使います。バックグラウンドの回収プロセスにも、この保存先が引き継がれます。

```bash
export AGENTRUN_HISTORY_DIR=/absolute/path/to/history
```

保存用 ID の `archive_id` は、元の実行 ID と `.agent-runs` の親ディレクトリの絶対パスから作るハッシュを組み合わせます。別プロジェクトで実行 ID が重なっても、履歴を上書きしません。Markdown は共通の保存先にのみ作成し、各実行の `live/history_export.json` からその場所を確認できます。以前のプロジェクト内に保存された履歴は移動しません。共通の索引に追加したい場合は、その実行の履歴を再保存してください。

実行情報には、次の二つの場所を区別して記録します。

| 項目 | 記録する場所 |
| --- | --- |
| `launcher_cwd` | `agentrun` を実行した投入元ホスト上のディレクトリの絶対パス |
| `repo` | `--repo` で指定した作業対象。コンテナでは `/workspace` に対応 |

後から別のディレクトリで履歴を保存し直しても、これらの値は変わりません。古い実行記録に `launcher_cwd` がない場合は `null` として保存します。作業対象や、コンテナ内の会話履歴に残る `cwd` から元の投入場所を推定して埋めることはしません。

### 保存する会話と出力

Markdown には、ユーザーの発言と、画面に表示されるアシスタントの応答を会話順に保存します。ツールの入力・結果、コマンド出力、記録されていれば終了情報やファイルの変更内容も、折りたたみ表示で収録します。

- Codex に標準出力・標準エラーの区別がない場合は、結合された出力を保存します。
- Claude のツール結果は、構造化されたデータとエラー文字列の両方に対応します。ツール結果をユーザーの発言として表示することはありません。
- サブエージェントの履歴と、`/new` で追加されたセッションは、別の節として収録します。
- 元の履歴に含まれる `source` / `originator` は実行情報に残します。オブジェクト形式の `source` にも対応します。

システム指示・開発者指示、内部の推論記録、画像のバイナリデータ、重複した API リクエスト本体は保存対象から除きます。Codex の同じ発言が複数のイベントに現れても、Markdown には重複して表示しません。

保存時には会話ファイル全体を読みます。末尾だけを読む `resume --preview` とは別の処理です。JSONL の最終行だけが途中で切れている場合は、その行を飛ばして注記します。途中の行が壊れている場合は、黙って欠落させず保存処理を失敗させます。

### 保存上の制限

Claude の長い出力は、永続化されたプロジェクト履歴や実行ごとの一時領域にある補助テキストファイルからも取り込みます。Claude の一時ディレクトリは `/scratch/claude` に設定し、投入元ホストから出力を回収できるようにしています。永続化対象外のパスは読みません。

補助ファイルの欠落やテキスト以外のデータ、分割・分岐前の履歴への参照は注記します。CLI が既に破棄した出力や、保存されていない過去の会話までは復元できません。元の JSONL と永続化された補助ファイルは、`.sessions/` や `scratch/` に残ります。

一回の実行につき、保存時点の Markdown 一式と SQLite の `conversations` テーブルの一行を作成します。再保存すると同じ行を更新します。再開した実行には新しい保存データを作り、セッションキーで以前の実行と関連付けます。以前の実行の保存データは変更しません。

共通の保存先にある Markdown と SQLite は、実行ディレクトリの改名やプロジェクトの削除後も残ります。ただし、再保存にはプロジェクト側の実行記録と元の会話履歴が必要です。履歴の保存ディレクトリは本人だけが利用できる権限とし、ファイルは `0600` で作成します。

### 手動保存と回収の再開

```bash
agentrun history                         # 最新の実行を保存
agentrun history RUN_ID                  # 指定した実行を再保存。改名後も指定可能
agentrun history /absolute/path/to/run
agentrun history --watch RUN_ID          # 投入元ホストで終了を待ち、履歴を回収
```

投入元ホストの再起動などで回収プロセスが止まった場合は、元の投入元ホストで `history --watch` を実行してください。

準備だけを行った後で `submit.sbatch` を手動投入した場合は、`live/slurm_job_id.txt` にジョブ ID が書かれてから回収したいホストで `history --watch` を実行するか、終了後に `history` を実行します。元のセッション記録が必要なため、会話の永続化に対応する前の実行は保存対象にできません。

保存に失敗すると、`live/history_export.json` と診断ログに記録します。エージェントの終了コードは変えず、一時ホームの削除も続行します。元の永続化済み履歴は残るため、後から再保存できます。

対話実行の終了処理では、履歴保存を最大 120 秒で打ち切ります。時間切れを記録して一時ホームの削除へ進むため、時間のかかる履歴は `agentrun history` で再保存してください。手動保存には、この終了処理用の制限時間はありません。回収時には `SQUEUE_PARTITION` などの表示用フィルタを無視し、実行中のジョブを見失わないようにします。

### SQLite に保存した会話の検索

SQLite には、`archive_id`（主キー）、`run_id`、`run_parent`、`agent`、`repo`、`launcher_cwd`、`session_key`、`markdown_path`、`metadata_json`、`markdown`、`updated_at` を保存します。Markdown 本文もデータベース内に含まれます。

次は本文を検索する例です。SQLite のコマンドや追加の Python パッケージは不要で、Python の標準ライブラリ `sqlite3` を使います。

```python
import os
from pathlib import Path
import sqlite3

root = Path(os.environ.get("AGENTRUN_HISTORY_DIR", "~/.agentrun/history")).expanduser()
with sqlite3.connect(root / "index.sqlite3") as db:
    rows = db.execute(
        "SELECT archive_id, agent, repo, launcher_cwd, markdown_path "
        "FROM conversations WHERE markdown LIKE ?",
        ("%experiment%",),
    ).fetchall()
```

## 対話による相互監査

Claude Code の作業を Codex に、Codex の作業を Claude Code に監査させられます。共通スキルの `cross-review` が、監査依頼、質問への回答、修正・反論後の再監査を案内します。監査は作業中の Slurm ジョブに割り当てられた資源で実行し、追加のジョブは投入しません。

両方の認証情報を投入元ホストで準備してください。既にログイン済みなら `agentrun auth import --all` で登録できます。相手側の認証がなくても通常の作業は開始できますが、監査の依頼は認証不足として失敗します。

作業エージェントには `cross-review` の MCP サーバーを自動登録します。MCP は、エージェントから監査用のツールを呼び出すための接続方式です。監査用 CLI は最初の依頼時に導入し、その実行中は再利用します。

### 監査の依頼と質疑応答

コンテナ内の作業エージェントに、例えば「cross-review を使って、この変更と研究上の主張を監査して」と依頼します。監査エージェントから質問が届くと、作業エージェントが理由と証拠を回答し、同じ監査会話を続けます。

質疑応答の途中では対象ファイルを変更せず、判定が返ってから修正や反論を行います。既定の上限は、初回と再監査を合わせて 2 ラウンド、各ラウンドの質疑応答は 3 往復です。初回で承認されれば終了できます。

CLI と MCP は同じ監査状態を扱います。CLI では、コンテナ内で次のように操作します。

```bash
agent-review run --request-id initial-review --kind research \
  --brief /runs/artifacts/review-brief.md --include /runs/artifacts/metrics.json
agent-review events REVIEW_ID --after 0 --wait-seconds 20
agent-review reply REVIEW_ID --request-id answer-1 --reply-to MESSAGE_ID \
  --message-file /runs/artifacts/review-answer.json
agent-review recheck REVIEW_ID --request-id recheck-1 \
  --response /runs/artifacts/review-response.json
agent-review status REVIEW_ID
```

イベント取得で返された `cursor` を、次回の `--after` に指定します。新しい操作には新しい `request_id` を使い、同じ操作を再送する場合だけ同じ ID を使います。MCP で開始した監査に CLI で回答することもできます。接続が切れても、会話と回数の上限は保持します。

回答ファイルの例です。`evidence` には、`/runs/reviews/REVIEW_ID/input/manifest.json` に記録されたコピー内の相対パスを指定します。新しい証拠を追加する場合は、`include` に元のファイルを明示します。取得したパスとハッシュは、追加の取得対象一覧に記録します。

```json
{
  "answers": [
    {
      "question_id": "q1",
      "answer": "回答と根拠",
      "evidence": ["source/evaluation.py"]
    }
  ],
  "questions": [],
  "include": []
}
```

### 修正・反論後の再監査

再監査は同じ `review_thread_id` の中で、新しい `review_id` を発行します。`recheck` / `review_recheck` の返り値から新しい `review_id` と `cursor` を受け取り、以後の状態確認・イベント取得・回答にはその ID を使ってください。以前の ID を参照すると、前ラウンドの確定済みの結果が返ります。

以前のすべての `finding_id` に対して、次のいずれかと理由・証拠を記録します。

| 値 | 意味 |
| --- | --- |
| `fixed` | 指摘を受けて修正した |
| `disputed` | 指摘に反論する |
| `deferred` | 対応を保留する |

```json
{
  "responses": [
    {
      "finding_id": "f1",
      "action": "disputed",
      "reason": "反論と根拠",
      "evidence": ["source/evaluation.py"]
    }
  ]
}
```

監査エージェントは、各指摘を `resolved`（解消）、`withdrawn`（撤回）、`unresolved`（未解消）、`insufficient_evidence`（証拠不足）で再判定します。作業エージェントが対応済みと宣言しただけでは、指摘を解消した扱いにしません。

### 対象ファイルと制限

Git で追跡しているソースコードと、作業開始時のコミットからの差分を取得します。未追跡ファイルや成果物は `--include` で明示してください。`--base COMMIT` で比較元を、`--exclude 'path/pattern/*'` で対象外のファイルを指定できます。

除外したファイルや、確認できないバイナリ・視覚資料は取得対象一覧に記録します。秘密情報、キャッシュ、シンボリックリンクを経由する入力は受け付けません。初期上限は、1 ファイル 4 MiB、入力全体で 32 MiB、1 万ファイルです。

### 中止・追加ラウンド・一括実行

監査を中止する場合は `agent-review cancel REVIEW_ID --request-id cancel-1` を使います。

ラウンドを追加するには、ユーザーの明示的な継続依頼が必要です。次のコマンドは、その依頼を記録して上限を変更する例です。期限は延長しません。

```bash
agent-review extend REVIEW_ID --request-id extend-1 --user-requested \
  --max-rounds 3 --reason '継続依頼の理由'
```

`agent-review run --one-shot --wait ...` は、質疑応答なしでまとめて監査する形式です。対話が使えない場合に自動で切り替わることはありません。

### 設定と保存先

起動前に投入元ホストで次の環境変数を設定すると、コンテナへ引き継ぎます。

| 変数 | 内容・既定値 |
| --- | --- |
| `AGENT_REVIEW_CODEX_MODEL` / `AGENT_REVIEW_CLAUDE_MODEL` | 監査に使うモデル。未指定なら各 CLI の既定値 |
| `AGENT_REVIEW_CODEX_EFFORT` / `AGENT_REVIEW_CLAUDE_EFFORT` | 監査時の推論強度。導入された CLI が対応する値を指定 |
| `AGENT_REVIEW_MAX_EXCHANGES` | ラウンド内の質疑応答の上限。既定は 3 往復 |
| `AGENT_REVIEW_ACTIVE_TIMEOUT` | ラウンド内の監査処理に使える合計時間。既定は 600 秒 |
| `AGENT_REVIEW_REPLY_TIMEOUT` | 一回の回答を待つ上限。既定は 600 秒 |
| `AGENT_REVIEW_THREAD_TIMEOUT` | 修正・回答待ちを含む監査全体の上限。既定は 3,600 秒 |

状態や判定は、次のように区別します。

| 値 | 読み方 |
| --- | --- |
| `success` | 判定を受け取れたという意味で、承認されたとは限らない |
| `approve` | 承認の判定。ただし、適用可否が `stale` や `incomplete` なら完了の根拠にはできない |
| `waiting_reply` | 質問への回答待ち |

初期版の監査は静的な確認です。学習やテストを独立に実行した保証は含みません。

各ラウンドの記録は `/runs/reviews/REVIEW_ID/` に保存します。`conversation.md`、`events.jsonl`、`review_findings.json`、`report.md`、`response.json` と、発言ごとのログが含まれます。

CLI が保存する元の履歴は、既存のセッション保存領域の `reviewers/PROVIDER/` に分け、作業セッションの再開対象には含めません。終了後は、ホスト側の履歴保存処理で両エージェントの会話と監査対話を `~/.agentrun/history/` の Markdown・SQLite に集約します。

MCP に必要なパッケージは、`mcp==1.26.0` を指定した uv 環境に取得し、`/cache/uv` を使います。初回は配布先への接続が必要です。イメージの再ビルドは不要です。詳細は[相互監査の設計書](CROSS_AGENT_REVIEW_DESIGN.md)を参照してください。

### 相互監査の検証

外部モデルを呼ばないローカルテストは、このリポジトリのルートから実行します。MCP の標準入出力による通信も検証します。

```bash
uv run --no-project --with mcp==1.26.0 python -m unittest discover -s tests -p 'test_cross_review*.py' -v
uv run --no-project python -m unittest discover -s tests -p test_review_launch.py -v
```

実環境では、両方の認証を準備し、`agentrun assist --agent claude` と `agentrun assist --agent codex` をそれぞれ起動します。小さな Git リポジトリの変更について `cross-review` を依頼し、両方向で質問への回答、修正・反論後の再監査まで進めてください。会話 ID、権限制限、作業エージェントの成果物、終了後の集約履歴を確認します。この試験では、実際のモデルの利用枠を消費します。

<a id="rust--日本語-lualatex"></a>

## Rust と日本語 LaTeX

`runtime/apptainer/base-system.def` に以下を含めています。追加前にビルドした `.sif` は計算ノードで再ビルドしてください。

| 用途 | 導入内容 |
| --- | --- |
| Rust | ビルド時点の最新安定版を rustup の最小構成で導入（`rustc` / `cargo` / 標準ライブラリ）。加えて `build-essential`、`pkg-config` |
| LaTeX 組版 | `texlive-luatex`、`texlive-latex-extra`、`texlive-fonts-recommended`、`texlive-science`（`siunitx` など） |
| 日本語組版 | `texlive-lang-japanese`（LuaTeX-ja、`ltjsarticle` を含む） |
| 自動ビルド | `latexmk` |
| 文献処理 | `biber`、`texlive-bibtex-extra`（`biblatex` を含む） |
| PDF 検証・画像化 | `poppler-utils`（`pdfinfo`、`pdffonts`、`pdftotext`、`pdftoppm` など） |
| 日本語フォント | `fonts-ipaexfont`（IPAex 明朝・ゴシック）、`fontconfig` |

Rust のコンパイラや標準ライブラリは `/opt/rustup`、rustup と cargo の実行ファイルは `/opt/cargo/bin` に配置します。コンテナ起動時に `PATH` と `RUSTUP_HOME` が設定されます。

cargo のキャッシュと `cargo install` で導入したファイルは、実行ごとの `$HOME/.cargo` に保存します。`$HOME/.cargo/bin` も `PATH` に含まれます。イメージ内の Rust を更新する場合は `build-images.sh --run --force` で再ビルドしてください。導入されるバージョンは、ビルド時点の最新安定版です。

コンテナ内での確認・利用例:

```bash
rustc --version
cargo --version
cargo build --release

# LuaLaTeX を指定する。biblatex で backend=biber を使う文書では Biber も自動実行される。
latexmk -lualatex -interaction=nonstopmode -halt-on-error main.tex
pdfinfo main.pdf
pdffonts main.pdf
pdftotext main.pdf main.txt
pdftoppm -f 1 -singlefile -png -r 150 main.pdf main-page1
```

日本語文書では、例えば次のように IPAex フォントを指定できます。

```latex
\documentclass{ltjsarticle}
\usepackage[ipaex]{luatexja-preset}
\begin{document}
日本語の本文。\textsf{ゴシック体の本文。}
\end{document}
```

定義ファイルの `%test` は、イメージのビルド時に次を自動検証します。

- 空の書き込み可能なホームディレクトリを使い、Rust 2024 エディションのプログラムをオフラインでコンパイル・実行する。
- `cargo install` の保存先を確認する。
- 日本語の明朝体・ゴシック体と文献を含む文書を、latexmk、LuaLaTeX、Biber でビルドする。
- Poppler で PDF 情報、IPAex フォントの使用と埋め込み、日本語と文献のテキスト抽出、PNG への変換を確認する。

既存イメージに対して再検証する場合も、計算ノードで実行してください。

```bash
srun --partition <partition> apptainer test --cleanenv --containall runtime/apptainer/base-system.sif
```

## 外部サービスの認証情報

<a id="secretsトークン系の環境変数のセットアップ任意"></a>

### 秘密情報を環境変数で渡す（任意）

Hugging Face のトークンなど、コンテナ内で環境変数として使いたい値は `secrets/.env` に書きます。GitHub のトークンはここには書かず、[GitHub 操作の仲介サービス](#github-cli-broker任意) を使ってください。

```bash
./install.sh --apply        # secrets/.env と secrets/gh.env が無ければテンプレートから作成（chmod 600）
$EDITOR secrets/.env        # 使う行のコメントを外して値を入れる
agentrun doctor --agent claude
```

`secrets/.env` は Git の管理対象から除外しています。テンプレート（`secrets/.env.example`）は全行コメントアウトされた状態で、以下の入力欄があります。`agentrun` の初回実行時にも、無ければ自動で作成されます。

```text
# HF_TOKEN=     huggingface_hub / hf CLI が自動で使用（hf auth login 不要）
```

書式は `KEY=VALUE` を 1 行に 1 つです。上記以外の変数も同じ書式で追加できます。

渡し方と見え方:

- 値は `apptainer exec --env-file <path>` で渡されます。ファイルはジョブ実行時に計算ノード上で Apptainer が読みます。
- この指定によって認証ファイル自体をコンテナへマウントすることはありません。
- `apptainer_exec.sh`、`submit.sbatch`、`capsule.yaml`、`dry-run` の出力には、ファイルのパスと変数名だけが出て、値は書かれません。
- **環境変数になった値はエージェントから読めます**（`env`、`/proc/self/environ` など）。隠せるのはファイルと実行の記録だけです。トークンは権限を絞り、有効期限を付けてください。
  - Hugging Face では、権限を細かく指定できる読み取り専用トークンを使います。利用申請が必要な公開モデルを取得する場合も、必要なリポジトリの読み取り権限に絞ってください。申請不要の公開モデルやデータセットの取得には、トークンは不要です。
- `secrets/.env` に `GH_TOKEN` を書くと、トークンがエージェントに直接渡るため警告が出ます。`secrets/gh.env` に移してください。

別のファイルを使う場合や、秘密情報の環境変数を渡さない場合:

```bash
agentrun assist --agent claude --secrets-file /path/to/other.env
agentrun assist --agent claude --no-secrets
export AGENTRUN_SECRETS_FILE=/path/to/other.env   # 常に別ファイルを使う
```

注意:

- ファイルがグループ / その他のユーザーから読める場合は警告が出ます（`chmod 600` してください）。
- `--repo` や `--bind` のマウント元に秘密情報のファイルが含まれると、`/workspace` などからエージェントに見えてしまうため警告が出ます。この設定リポジトリ自体を `--repo` に指定して起動する場合（`--repo` を省略してこのディレクトリで実行した場合も含む）が該当します。

<a id="github-cli-broker任意"></a>

### GitHub 操作の仲介サービス（任意）

エージェントに GitHub の認証情報を一切渡さずに、許可した `gh` コマンドだけを使わせる仕組みです。

```bash
./install.sh --apply        # secrets/gh.env が無ければテンプレートから作成（chmod 600）
$EDITOR secrets/gh.env      # GH_TOKEN= のコメントを外して値を入れる
agentrun doctor --agent claude   # gh-broker:token が [OK] になることを確認
```

`secrets/gh.env` に `GH_TOKEN` が設定されていると、すべての実行で仲介サービスが起動します。実行ごとに止める場合は `--no-gh-broker` を付けます。

仕組み:

- `apptainer_exec.sh` はエージェントのコンテナより先に、**別の Apptainer コンテナ** で仲介サービス（`runtime/gh-broker/gh_broker.py`）を起動します。`GH_TOKEN` は `--env-file secrets/gh.env` でこのコンテナにだけ渡ります。
- エージェントのコンテナでは `/usr/local/bin/gh` が `runtime/gh-broker/gh-client` に置き換わります。クライアントはコマンドを Unix ソケット（計算ノードの `/tmp/agentrun-gh.*`、コンテナ内では `/opt/gh-broker/gh.sock`）で仲介サービスに送り、結果を受け取るだけです。
- `--containall` により 2 つのコンテナは PID 名前空間が分かれているため、エージェントから仲介サービスのプロセスや環境変数は見えません。`secrets/gh.env` もどちらのコンテナにもマウントされません。
- 仲介サービスは `runtime/gh-broker/allowlist.txt` に書かれたコマンドだけを、書かれた位置引数と長形式のオプションだけで実行します。それ以外（未記載のサブコマンド・オプション、短形式のオプション、URL、余分な位置引数）はすべて拒否します。既定の許可リストは research-harness（RDH）が発行する gh 呼び出しの全体です。

  ```text
  --version
  auth status
  repo view [repo]: --json
  issue create: --title --body-file --label --repo
  issue view <number>: --json --repo
  issue list: --state --limit --json --repo
  issue comment <number>: --body-file --repo
  issue close <number>: --comment --repo
  pr create: --title --body-file --head --base --draft --repo
  pr view <number|branch>: --json --repo
  pr list: --head --state --limit --json --repo
  pr edit <number|branch>: --body-file --repo
  ```

  書式は `<subcommand> [位置引数] : --flag ...` です。位置引数は `<number>`（Issue/PR 番号）、`<number|branch>`、`[repo]`（`OWNER/NAME`）のいずれかで、`<>` は必須、`[]` は省略可です。URL は受け付けないため、位置引数から別のリポジトリに届くことはありません。オプションの値も検証します（`--body-file` は `-` のみ、`--repo` と `repo view` の引数は `OWNER/NAME`、`--head`/`--base` はブランチ名、`--state`/`--limit`/`--json` は形式）。値を取らないオプションは `gh_broker.py` の `BOOLEAN_FLAGS`（既定は `--draft`）に登録されたものだけです。
- `api`（任意の GitHub API をトークン付きで呼べるため）、`auth token`・`--show-token`、`issue edit`、`pr comment`、`pr merge`、`--attach` などローカルファイルを読むオプションは許可しません。Issue のコメントの読み出しは `gh issue view <番号> --json comments` を使います（100 件を超えるコメントも全件返ることを確認済み）。
- **書き込み先リポジトリの固定**: `secrets/gh.env` の `GH_BROKER_REPOS=owner/name[,owner/name]` を設定すると、`--repo`、`repo view` の引数、クライアントが推定したリポジトリはこのリストに含まれる必要があります。1 つだけ書いた場合はそれが既定の対象になり、推定したリポジトリが違っていても（フォーク先の `origin` など）固定したリポジトリに向けます。未設定の場合はトークンが届く全リポジトリが対象になるため、`doctor` が WARN を出します。
- 対象リポジトリは `--repo`、`GH_REPO`、またはコンテナ内 Git リポジトリの `origin` リモートからクライアントが推定し、仲介サービスに渡します。仲介サービスは空の作業ディレクトリで `gh` を実行し、エージェントが書き換えられる Git の設定を読みません。
- `--body-file FILE` はクライアント（コンテナ内）がファイルを読み、`--body-file -` に置き換えて標準入力で送ります。仲介サービス側でパスを開くことは一切ありません。そのため仲介サービス側で読めるパスを制限する必要はありません（エージェントはコンテナ内で読めるファイルなら `--body-file` を使わなくても本文に書けるため、クライアント側でのパス制限は防御になりません）。
- `pr create` で `--head` を省略すると、クライアントがコンテナ内の現在のブランチを `--head` として付けます（仲介サービスは Git リポジトリの外で `gh` を実行するため）。
- 仲介サービスの返す出力とログからは、トークン文字列を `***` に置き換えます。実行・拒否したコマンドは `live/gh_broker.log` に記録されます（トークンは含みません）。`issue close --comment` の本文と `--title` はログに文字数だけを残します（`issue close` には `--body-file` が無く、本文がコマンドの引数に含まれるため）。
- 実行が終わると仲介サービスは停止し、ソケットディレクトリは削除されます。

制限と注意:

- 対話的な操作（プロンプト、`--web`、`--editor`）は使えません。Issue / PR 番号は明示してください（現在のブランチからの推定は仲介サービス側ではできません）。`pr create --fill` のようにローカルの Git リポジトリを参照する使い方もできません。
- `git push` は仲介サービスの対象外です。コンテナには GitHub の認証情報が無いため、HTTPS リモートへのプッシュは失敗します（`gh auth setup-git` もトークンが無いので使えません）。プッシュが必要な場合は、リポジトリを限定した SSH デプロイキーを渡す（鍵ファイル自体はエージェントから読めます）か、ホスト側でプッシュしてください。
- エージェントは許可リストの範囲内でなら `gh` を自由に使えます（Issue の大量作成など）。許可リストとトークンの権限（例: Issue・プルリクエストの読み書きとメタデータの読み取りだけを許可し、対象リポジトリも限定する）の両方で絞ってください。
- コンテナ内の `/usr/bin/gh` を直接呼ぶことはできますが、認証情報が無いため認証の必要な操作は失敗します。
- `gh` はイメージ（`base-system.def`）に入っています。`gh` 追加前にビルドした `.sif` の場合は再ビルドしてください。`git pull` で `base-system.def` が更新されていれば `build-images.sh --run` でシステムイメージが作り直されます。確実に作り直す場合は `--run --force` を使います。
- 隔離は Apptainer の名前空間と「トークンファイルをマウントしない」ことに依存しています。同じ UID で動くため、カーネルの脆弱性などによるコンテナからの脱出までは防げません。
- `git push` の禁止（Claude の拒否ルール、Codex の実行ルール、`git_branch_guard.py`）はコマンド文字列での判定で、`git -C . push` などは通ります。プッシュの可否は、コンテナにプッシュ用の認証情報を渡さないこと、トークンの権限、リモート側のブランチ保護で決まります。

## 設定の管理

<a id="agent-差分"></a>

### エージェントごとの設定

#### Claude Code

コンテナパス:

```text
/home/sandbox/.claude/settings.json
/home/sandbox/.claude/CLAUDE.md
/home/sandbox/.claude/hooks/
/home/sandbox/.claude/skills/
```

ホスト側のファイル:

| パス | 内容 |
| --- | --- |
| `agents/claude/CLAUDE.md` | → `../../common/AGENTS.md` |
| `agents/claude/skills` | → `../../common/skills` |
| `agents/claude/settings.json` | 基本設定 |
| `agents/claude/settings.assist.json` | assist 用の追加設定 |
| `agents/claude/settings.experiment.json` | experiment 用の追加設定 |
| `agents/claude/hooks.manifest.json` | フックの定義ファイル |

起動コマンド:

```text
対話式 assist        cd /workspace && claude --dangerously-skip-permissions
バッチ実行           cd /workspace && claude --print --dangerously-skip-permissions
```

認証 (認証ストア):

```text
$HOME/.agentrun/auth/claude/.claude/.credentials.json
$HOME/.agentrun/auth/claude/.claude.json
```

マウント:

| パス | 内容 |
| --- | --- |
| `agents/claude/CLAUDE.md` | → `/home/sandbox/.claude/CLAUDE.md:ro` |
| `container_config/settings.json` | → `/home/sandbox/.claude/settings.json:ro` |
| `common/hooks` | → `/home/sandbox/.claude/hooks:ro` |
| `agents/claude/skills` | → `/home/sandbox/.claude/skills:ro` |

#### Codex

コンテナパス:

```text
/home/sandbox/.codex/config.toml
/home/sandbox/.codex/AGENTS.md
/home/sandbox/.codex/rules/
/home/sandbox/.codex/skills/
/etc/codex/requirements.toml
```

ホスト側のファイル:

| パス | 内容 |
| --- | --- |
| `agents/codex/AGENTS.md` | → `../../common/AGENTS.md` |
| `agents/codex/skills` | → `../../common/skills` |
| `agents/codex/config.toml` | 基本設定（現在は [tui] のみ） |
| `agents/codex/config.assist.toml` | assist 用設定（現在は [tui] のみ） |
| `agents/codex/config.experiment.toml` | experiment 用設定（現在は [tui] のみ） |
| `agents/codex/hooks.manifest.json` | フックの定義ファイル |
| `agents/codex/requirements.toml` | 定義ファイルから生成した管理対象フックの設定 |
| `agents/codex/rules/` | コマンド実行ルール。禁止ルールのみを使用。承認を省略して起動するため許可ルールは使わない |

起動コマンド:

```text
対話式 assist        cd /workspace && codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --cd /workspace
バッチ実行           cd /workspace && codex exec --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --skip-git-repo-check --cd /workspace
```

認証 (認証ストア):

```text
$HOME/.agentrun/auth/codex/.codex/auth.json
```

マウントと一時配置するファイル:

| パス | 内容 |
| --- | --- |
| `agents/codex/requirements.toml` | → `/etc/codex/requirements.toml:ro` |
| `agents/codex/AGENTS.md` | → `/home/sandbox/.codex/AGENTS.md:ro` |
| `agents/codex/rules` | → `/home/sandbox/.codex/rules:ro` |
| `container_config/config.toml` | → `<run_dir>/home/.codex/config.toml` |
| `common/skills/*` | → `<run_dir>/home/.codex/skills/*`（シンボリックリンク） |

Codex の設定は、実行ごとのホームディレクトリへコピーするため書き込み可能です。信頼設定の保存エラーが出る場合は `/home/sandbox/.codex/config.toml` が読み取り専用バインドマウントになっていないか確認してください。

<a id="common-instructions"></a>

### 共通の指示の変更

共通の指示を変更する場合は、次のファイルを編集します。

```text
common/AGENTS.md
```

各エージェントの指示ファイルは共通ファイルへのシンボリックリンクです。

| パス | 内容 |
| --- | --- |
| `agents/claude/CLAUDE.md` | → `../../common/AGENTS.md` |
| `agents/codex/AGENTS.md` | → `../../common/AGENTS.md` |

編集後:

```bash
agentrun validate
```

<a id="skills-maintenance"></a>

### スキルの管理

共通スキルは以下に置きます。

```text
common/skills/
```

既存スキルの中身だけを編集する場合、通常同期は不要です。

```bash
agentrun validate
```

スキルディレクトリを追加・削除した場合は、シンボリックリンク更新のため同期します。

```bash
agentrun sync-claude
agentrun sync-codex
agentrun validate
```

<a id="公開-skills-の取り込み"></a>

#### 外部スキルの取り込み

`skills/<name>/SKILL.md` というレイアウトを持つ外部リポジトリ（ローカルパス、または GitHub URL）から、`common/skills/` へ一括で取り込めます。

```bash
# ローカルの取り込み元ディレクトリから: SOURCE_DIR/skills/ 配下の全サブディレクトリを取り込み（SKILL.md がないものはスキップ）
agentrun skill-install ../some-skills-repo

# GitHub URL を直接渡す場合: 一時ディレクトリに履歴を浅く複製 -> skills/* だけ common/skills/ へコピー -> 複製したリポジトリを削除
agentrun skill-install https://github.com/softaworks/agent-toolkit.git

# 特定のスキルだけ選んで取り込み（ローカル/URL どちらでも可）
agentrun skill-install https://github.com/softaworks/agent-toolkit.git react-dev mui

# 既に common/skills/<name> が存在する場合は上書きしない（--force で上書き）
agentrun skill-install ../some-skills-repo react-dev --force
```

URL 判定は `http(s)://`・`git@`・`ssh://`・`git://`・`*.git` のいずれかにマッチした場合で、この場合のみ `git clone --depth 1` を一時ディレクトリに対して行い、コピー完了後に即座に削除します（`common/skills/` にはクローン全体ではなく `skills/*` の中身だけが残ります）。取り込みに成功したスキルが1件以上あれば、内部で `sync-claude` / `sync-codex` を自動実行します。取り込み後は `agentrun validate` で確認してください。

<a id="デフォルト-skill-の解説"></a>

#### 標準搭載スキルの一覧

`common/skills/` に含まれるスキルとその役割を以下に示します。各スキルは `SKILL.md` として格納されており、冒頭の定義 (`name:` / `description:`) によってエージェントがいつ参照すべきかを判断します。

| スキル | 説明 |
| ----- | ---- |
| `uv` | Python プロジェクト・パッケージ・スクリプトの管理に使う `uv` コマンドのガイドです。`uv add`/`uv run`/`uvx` の使い分けや、仮想環境の作成・管理方法を説明します。 |
| `agentrun-contract` | agentrun コンテナ内でエージェントが書くべき出力ファイル・フォーマット・書き込みタイミングの一覧です。`live/status.json`・`artifacts/report.md` などの必須ファイルとモード別の追加要件、`verify-run` が何をチェックするかを記述します。 |
| `ruff` | Python ファイルを編集した後の静的検査・整形手順です。`post_edit_format.py` フックはフォーマッタを自動実行しないため、`uvx ruff check --fix` と `uvx ruff format` を手動実行する必要があることを説明します。 |
| `experiment-report` | `experiment`・`campaign`・`review`・`multi-review` 各モードで書くべきモード固有ファイルのスキーマです。`artifacts/proposed_next.yaml`・`artifacts/proposed_train.sbatch`・`reviews/review_findings.json`・`reviews/disagreements.json` などのフォーマットを記述します。 |
| `pytest` | `uv run pytest` によるテスト実行と、結果を `/runs/live/stdout.log`、`artifacts/metrics.json` に記録する方法を説明します。プロジェクトのテストには uv を使い、システム Python はコンテナの起動やフックなどの基盤処理に使います。 |
| `research-latex` | 学術論文・技術報告書・モノグラフのテンプレートを使い、日英の研究文書を PDF にします。LuaLaTeX、Biber、構造検証、目視確認用のページ画像生成に対応します。付属の例は架空のデータです。 |
| `yomiyasu` | 意味を保ちながら日本語を推敲します。文章の点検と修正前後の比較に使うツールを含みます。数値や研究上の主張の正しさは、別途検証します。 |
| `cross-review` | もう一方のエージェントに監査を依頼し、質問への回答、修正・反論の記録、再監査を進めます。 |

標準搭載のスキルは、この 8 種類です。

#### research-latex による研究文書の作成

`research-latex` は、読み取り専用でマウントされた共通スキルを通じて Claude Code と Codex の両方で使えます。スキルの更新だけならイメージの再ビルドは不要で、次に起動した実行から反映されます。ただし、テンプレートが使う `siunitx` には `texlive-science` が必要です。導入前のイメージを使っている場合は、先に再ビルドしてください。

システム Python は、フック、エージェント起動時の情報取得、GitHub 操作の仲介などの基盤処理用に残しています。`research-latex` のツールは `uv run --no-project python` で動かし、追加の Python パッケージは使いません。TeX Live と Poppler は OS パッケージとして導入しています。

コンテナ内で次のように実行します。スキルのディレクトリは読み取り専用なので、生成する文書は `/runs/artifacts` など別の場所に置いてください。

```bash
SKILL_ROOT=/home/sandbox/ai-agent-config/common/skills/research-latex
REPORT_DIR=/runs/artifacts/research-report
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" doctor
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init --template technical --output "$REPORT_DIR"
# 提出前に、架空のサンプルを実際の研究内容に置き換える
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build --project "$REPORT_DIR"
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" render --project "$REPORT_DIR" --all --dpi 150
```

提出前に、生成したすべてのページ画像を目視で確認してください。構造検証だけでは、文字の重なりや改ページなどの見た目は確認できません。

<a id="japanese-prose-editing-with-yomiyasu"></a>

#### yomiyasu による日本語の推敲

`yomiyasu` も Claude Code と Codex で共有します。[nanaism/yomiyasu のコミット 60bf877](https://github.com/nanaism/yomiyasu/tree/60bf877acebc86651e0b67d70112a66245f87758/skills/yomiyasu) から取り込み、MIT ライセンス、Unicode のライセンス告知、参考資料、文章確認用のスクリプトを含めています。この環境向けの説明とコマンド例は uv に合わせていますが、確認用スクリプトは取り込み元から変更していません。

```bash
SKILL_ROOT=/home/sandbox/ai-agent-config/common/skills/yomiyasu
uv run --no-project python "$SKILL_ROOT/scripts/yomiyasu_lint.py" /runs/artifacts/report.md
uv run --no-project python "$SKILL_ROOT/scripts/yomiyasu_diff.py" /runs/before.md /runs/after.md --stance=説明
```

日本語の執筆や推敲に使います。指定された報告書の形式や、構造化された出力の仕様は維持してください。点検結果は修正候補であり、自動的に正しい修正と判断するものではありません。研究の数値、単位、数式、引用、主張の強さは、元の資料と照合して別途確認します。

LaTeX 文書では、TeX コマンドや数式を変えずに本文を推敲し、その後 `research-latex` でビルドして PDF を確認します。

ツールは Python の標準ライブラリだけを使います。追加の OS・Python パッケージやイメージの再ビルドは不要で、新しく起動したコンテナから利用できます。

<a id="hooks-maintenance"></a>

### フックの管理

フック実装は共通です。

```text
common/hooks/
```

ただし、どのフックをどのエージェントで使うかはエージェントごとの定義ファイルで管理します。

```text
agents/claude/hooks.manifest.json
agents/codex/hooks.manifest.json
```

既存フックの中身だけを編集する場合:

```bash
agentrun validate
```

フックを追加・削除・リネームした場合:

```bash
agentrun sync-claude
agentrun sync-codex
agentrun validate
```

全ての `common/hooks/*.py` は、各エージェントの定義ファイルで `active`（有効）または `ignored`（対象外） に分類されている必要があります。未分類フックがあると `validate` は失敗します。

両エージェントの定義ファイルは同一のイベント × 照合条件形式を使います。

<a id="デフォルト-hook-の解説"></a>

#### 標準搭載フックの一覧

`common/hooks/` に含まれるフックとその役割を以下に示します。

<a id="pretooluse-コマンド実行フィルタ"></a>

##### 実行前のコマンド検査（PreToolUse）

これらはエージェントがコマンド実行ツール（Claude / Codex の `Bash`）を呼ぶ前に発火します。

| フック | 役割 |
| ---- | ---- |
| `block_dangerous_command.py` | `rm -rf /`・`rm -rf ~`、`mkfs`、`ssh`、`sudo` と、秘密ファイル（`.ssh/`、`id_rsa`/`id_ed25519`、`auth.json`、`.credentials.json`、`.env`/`.env.*`、`secrets/`、`.bashrc` など）へのアクセスをブロックします。判定はファイル名・パスだけで、`token`・`secret` といった単語（`AutoTokenizer`、`--max-new-tokens` など）では止めません。環境変数の値は対象外です。コマンド実行ツールとファイル系ツール（`Read` / `Edit` / `Write` / `apply_patch` など）の両方に適用されます。Codex の `apply_patch` はパッチ本文ではなく、対象ファイルのパス（`*** Update File:` などの行）だけを判定します。 |
| `check_login_node.py` | Slurm ログインノード上での計算用コマンド（`python`、`pytest`、`jupyter`、`torchrun` 等）をブロックします。`SLURM_JOB_ID` が設定されていない場合のみ動作するため、計算ノード内では処理を制限しません。 |
| `check_pip_forbidden.py` | `pip` の直接呼び出しと `uv pip install`/`uninstall`/`sync`/`compile` をブロックします。パッケージ管理は `uv add`/`uv remove` を使います。`uv pip list`/`show`/`freeze`/`check` は許可されます。 |
| `check_sbatch_forbidden.py` | Slurm ジョブ割り当ての内部（`SLURM_JOB_ID` が設定されている環境）での `sbatch`/`salloc` 呼び出しをブロックします。ネストしたジョブ投入を防ぎます。 |
| `git_branch_guard.py` | `git merge`、`git rebase`、`git push`、`.git` ディレクトリへの直接操作をブロックします。Claude では定義ファイルの `if: "Bash(git *)"` フィルタにより、git コマンド以外では発火しません。コマンド文字列での判定なので、`git -C . push` のような書き方や `gh pr merge`・`gh api` は止められません。プッシュやマージを確実に防ぐには、GitHub トークンの権限とリモート側のブランチ保護で制限してください。 |

<a id="posttooluse-コマンド実行後"></a>

##### コマンド実行後の処理（PostToolUse）

コマンド実行ツールが完了した後に発火します。

| フック | 役割 |
| ---- | ---- |
| `git_worktree_auto_create.py` | `git checkout -b <branch>` または `git switch -c <branch>` の直後に、`../<branch>` に作業ツリーを自動作成します。 |
| `update_run_status.py` | 実行されたコマンドのツール名とコマンド文字列を `live/command_log.jsonl` に追記し、`live/status.json` を更新します。コマンドの出力は記録しません（`env` の結果などから秘密情報の値が実行ディレクトリに残るのを防ぐため）。書き込み先は `AGENTRUN_DIR`、未設定なら `/runs` です。 |

<a id="posttooluse-ファイル編集後"></a>

##### ファイル編集後の処理（PostToolUse）

ファイル編集ツール（Claude の `Edit` / `Write`、Codex の `apply_patch`）が完了した後に発火します。

| フック | 役割 |
| ---- | ---- |
| `post_edit_format.py` | 編集イベントを `live/events.jsonl` に記録します。フォーマッタは自動実行しません。フォーマットが必要なプロジェクトではエージェント自身がコマンドとして実行するか、別フックに追加してください。 |

<a id="stop"></a>

##### セッション終了時の処理（Stop）

エージェントセッションが終了するときに発火します。

| フック | 役割 |
| ---- | ---- |
| `stop_notify.py` | Slack Incoming Webhook で完了通知を送ります。スクリプト内の `SLACK_WEBHOOK_URL` に実際の URL を設定してください。未設定のままでもフックは失敗せず、通知をスキップします。エージェント種別（Claude / Codex）を受信データから自動検出します。 |
| `summarize_session.py` | `artifacts/report.md` が存在しない場合にプレースホルダを作成します。エージェントが報告書を出力しなかったときに `verify-run` を通過させるための最低限の保護です。 |

<a id="install--uninstall"></a>

## コマンドの登録と削除

登録内容の確認のみ:

```bash
./install.sh
```

実際にシンボリックリンクを作成:

```bash
./install.sh --apply
```

削除内容の確認のみ:

```bash
./uninstall.sh
```

実際にシンボリックリンクを削除:

```bash
./uninstall.sh --apply
```

`install.sh --apply` は、コマンドと Bash 補完のシンボリックリンクを登録し、未作成の秘密情報ファイルをテンプレートから用意します。`uninstall.sh --apply` は、コマンドと補完の登録を削除します。リポジトリ内の設定、秘密情報ファイル、`.agent-runs/` は削除しません。

## 実装範囲と終了処理

### 現在の実装範囲

実装済み:

- 単一エージェントによる `assist`
- 単一エージェントによる `assist --submit`
- 単一エージェントによる `experiment --submit`
- 単一エージェントによる `campaign --submit`
- 単一エージェントによる `review --submit`
- 単一エージェントによる `multi-review --submit`
- `dry-run`
- `validate`
- `doctor`
- `sync-claude`
- `sync-codex`
- 実行状態・ログ・一覧・保存先・成果物の確認
- 基本動作確認用のひな型
- `resume` による会話の再開と、Markdown・SQLite への履歴保存
- `cross-review` による対話式の相互監査
- 計算ノードの SSD 領域の条件付きマウント

未実装またはひな型段階:

- 複数の作業エージェントを同時に起動・管理する処理
- すべての作業に対する相互監査の強制実行（依頼に基づく対話監査は実装済み）
- `multi-review` で複数 `sbatch` を発行して結果を自動集約する処理
- `campaign` の提案を実際の学習ジョブに接続する自動制御

`--reviewers`, `--target-diff`, `--target-report`, `--agents` は現状ではプロンプトに追記されるだけです。複数エージェントの起動や出力集約は行いません。

<a id="runtime-fixes-from-agent-capsule"></a>

### 実行時の保護と終了処理

同じ秒に複数回起動しても、実行ディレクトリは別々に作成します。バッチ実行・対話実行・再開は `--nodes=1 --ntasks=1` を明示し、同じリポジトリでの同時実行は `.agentrun.lock` で防ぎます。ロック用のファイル記述子は `srun` やコンテナへ渡しません。

投入元ホストの監視処理は、30 秒間隔で Slurm ジョブの終了を確認します。終了済みなのに `srun` が応答しない場合はローカルクライアントを停止して端末とロックを解放します。照会障害や実行中のジョブは終了済みと扱いません。端末復元、セッション確定、一時ホームの削除にも時間制限があります。

一時ホームの削除は最大 5 回再試行し、NFS の `.nfs*` などによる失敗を `live/home_cleanup.log` に記録します。15 秒の削除制限後も失敗する場合は警告します。Codex の実行中の補助プログラムはコンテナ内 `/tmp/agentrun-codex.*` に置いて終了時に削除し、大きいインストーラの圧縮ファイルは実行ごとのキャッシュ内に置きます。

エージェントと既存の GitHub 仲介サービスは計算ノードの `/etc/resolv.conf`・`/etc/hosts` を読み取り専用でバインドします。明示したバインドを使い、ホストの `APPTAINER_BIND*` 等による意図しない追加マウントと、GitHub トークンのエージェント側への環境変数注入を除きます。仲介サービスの認証は従来どおり `secrets/gh.env` です。仲介サービスが起動できない場合はエージェント起動前に失敗します。

`artifacts/environment.txt` は Slurm の割り当て資源、`PATH`・`PWD`・`HOME`・言語・地域設定などの許可した項目だけを記録し、認証情報を含む環境全体は保存しません。

取り込み元と採否は [不具合修正の取り込み記録](RUNTIME_BACKPORTS.md) に記録しています。

<a id="smoke-tests"></a>

## 基本動作のテスト

### Dockerによる疑似クラスタの検査

手元の Docker 上に投入元ホストと計算ノードを作り、実際の Slurm と Apptainer で主要機能を確認できます。本番の認証情報やモデルの呼び出しは不要です。カプセルのルート（`install.sh` があるディレクトリ）で実行してください。

```bash
tests/slurm/docker/run.sh
```

対話・バッチ起動、時間切れ後の再開、マウント、履歴保存、CLI・MCP による相互監査などの結合テストと、既存の Python 回帰テストを実行します。必要な Docker 環境、検証範囲、ログの保存先は[疑似クラスタのテスト手順](../tests/slurm/docker/README.md)を参照してください。

### 実クラスタでの基本動作の確認

`agentrun smoke-test` は、実行ディレクトリと `submit.sbatch` を生成する基本動作を確認するための軽量なひな型です。

準備のみ:

```bash
agentrun smoke-test --agent codex --partition <partition>
```

Slurm に投入:

```bash
agentrun smoke-test --agent codex --partition <partition> --submit
```

この基本動作テストでは、認証済みのモデルから応答を得られるかまでは確認しません。Creator 計算ノード向けには、追加の `assist-pty`、`codex-assist-pty`、`codex-auth` もあります。これらは、コンテナ内でのファイルの見え方、Codex の設定への書き込み、認証済みの `codex exec`、管理対象フックの起動を確認する開発者向けの Slurm テストです。

<a id="troubleshooting"></a>

## 問題が起きたとき

### `agentrun` が見つからない

```bash
./install.sh --apply
which agentrun
```

`$HOME/.local/bin` が `PATH` に入っていない場合はシェルの設定を確認してください。

<a id="doctor-が-auth-を-fail-にする"></a>

### `doctor` で認証の確認が失敗する

認証ストア (`$HOME/.agentrun/auth/`) とホスト両方にファイルが存在しない場合に FAIL になります。

```bash
agentrun auth status
agentrun auth login --agent NAME
agentrun doctor --agent NAME
```

認証ファイルはリポジトリに保存しません。認証ストアから `<run_dir>/home/` へ一時配置され、ジョブ終了後に削除されます。

<a id="token-が期限切れ認証エラーが出る"></a>

### トークンの期限切れ・認証エラーが出る

ジョブの途中や次回実行時に認証エラーになった場合は、再ログインして認証ストアを更新します。

```bash
agentrun auth login --agent NAME
```

`auth login` はホスト CLI でのログイン（`claude auth login` / `codex login`）と認証ストアへのインポートを一括で実行します。

<a id="capsule-の中で-apptainer-exec-が失敗するnested-apptainer--squashfuse_ll-エラー"></a>

### コンテナ内での Apptainer 実行が失敗する

既定の構成では、コンテナ内から FUSE を使えません。`--containall` により `/dev` が最小構成に置き換わるため、計算ノードに `/dev/fuse` があってもコンテナからは見えません。この状態でコンテナ内からさらに `apptainer exec` を実行すると、内側の `.sif` をマウントできず、`squashfuse_ll` のエラーになります。

必要な条件は 3 つで、どれが欠けても同じような失敗になります。

1. **計算ノードに `/dev/fuse` があること** — `agentrun doctor` が `fuse:/dev/fuse` として表示します。
   通常は `crw-rw-rw-` で全ユーザーが開けます。
2. **コンテナに `/dev/fuse` がバインドされていること** — `--allow-fuse` を付けます。

   ```bash
   agentrun assist --agent claude --gpus 1 --allow-fuse
   ```

   毎回付けたくない場合は `export AGENTRUN_ALLOW_FUSE=1` をシェル設定に入れてください。
   個別の実行で無効化したいときは `--no-allow-fuse` を使います。
3. **イメージに `libfuse3` / `liblzo2` が入っていること** — squashfuse_ll がこれらに動的にリンクしています。
   `runtime/apptainer/base-system.def` に `libfuse3-3` `liblzo2-2` `squashfuse` `fuse3` を含めてあるので、
   イメージを再ビルドすれば満たされます。

   ```bash
   srun --partition <partition> runtime/apptainer/build-images.sh --run
   agentrun doctor        # fuse:image-libs が [OK] になることを確認
   ```

`base-system.def` を変更した場合はシステムイメージを再ビルドしてください。
更新日時の判定で作り直されない場合（`.def` を更新日時を保持してコピーした場合など）は `--run --force` を使ってください。

なお `--allow-fuse` はコンテナに FUSE マウント能力を与えるため、隔離をやや緩めます。
入れ子のコンテナを実際に必要とする実行だけで有効化してください。

<a id="dry-run-の-directory-が存在しない"></a>

### `dry-run` に表示されたディレクトリが存在しない

正常です。`dry-run` は副作用なしの実行計画表示だけを行います。実体を作るには `assist`, `assist --submit`, `experiment --submit` などを実行してください。

### `status` が `{}` のまま

`.agent-runs/latest` が準備済みの実行または未完了実行を指している可能性があります。

```bash
agentrun open-run .agent-runs/latest
agentrun verify-run .agent-runs/latest
```

### `verify-run` が `artifacts/report.md` で失敗する

エージェントが必須成果物を作っていない状態です。Slurm ジョブの終了コードが 0 でも、出力要件を満たしていなければ `verify-run` は失敗します。

<a id="codex-trust-persistence-error"></a>

### Codex の信頼設定を保存できない

`/home/sandbox/.codex/config.toml` は、実行ごとのホームに置かれた書き込み可能なファイルである必要があります。読み取り専用の `:ro` でマウントされていると、信頼設定を保存できません。

`codex-assist-pty` 基本動作テストで書き込み可能設定を確認できます。

<a id="hooks-が発火しない"></a>

### フックが動かない

まずマウントと生成された設定を確認します。

```bash
agentrun dry-run assist --agent codex --show-mounts "フックの設定確認"
agentrun validate
```

Codex の実効フック経路は `/etc/codex/requirements.toml` です。Claude は `/home/sandbox/.claude/hooks/` を使います。

<a id="command-reference"></a>

## コマンド一覧

```text
agentrun agents
agentrun validate
agentrun doctor [--agent NAME|--all]
agentrun auth login --agent NAME|--all
agentrun auth import --agent NAME|--all
agentrun auth status [--agent NAME]
agentrun auth reset --agent NAME
agentrun dry-run MODE [options] PROMPT
agentrun assist [options] [PROMPT]
agentrun assist --submit [options] PROMPT
agentrun experiment|campaign|review|multi-review [options] PROMPT
agentrun wizard [options] [PROMPT]
agentrun resume [RUN_ID|RUN_DIR] [--time HH:MM:SS] [--mem SIZE] [--cpus N] [--bind SRC:DST[:OPTIONS]]
agentrun resume --list
agentrun resume RUN_ID --preview
agentrun smoke-test [--agent NAME] [--submit]
agentrun init-goal
agentrun sync-claude
agentrun sync-codex
agentrun skill-install SOURCE_DIR|GIT_URL [SKILL_NAME...] [--force]
agentrun status
agentrun logs [--follow]
agentrun tail
agentrun list-runs
agentrun open-run [RUN_DIR]
agentrun verify-run [RUN_DIR|--run-id RUN_ID]
agentrun history [RUN_ID|RUN_DIR] [--watch]
```

### 主なオプション

| オプション | 内容 |
| --- | --- |
| `--agent NAME` | `codex` または `claude`。省略時は `claude` |
| `--repo PATH` | `/workspace` にマウントする作業リポジトリ。省略時は現在のディレクトリ |
| `--goal PATH` | 目標を記述した YAML ファイル |
| `--gpus N` | GPU 数。既定は 0 |
| `--mem SIZE` | メモリ量。例: `16000M`。省略時は実行プロファイルの既定値 |
| `--cpus N` | CPU コア数。省略時は実行プロファイルの既定値 |
| `--time HH:MM:SS` | 実行時間の上限。省略時は実行プロファイルの既定値 |
| `--partition NAME` | Slurm のパーティション。省略時は `AGENTRUN_SLURM_PARTITION`、未設定ならクラスタの既定値 |
| `--bind SRC:DST[:OPTIONS]` | 追加マウント。複数回指定可能。権限は `ro` または `rw` |
| `--allow-fuse` | `/dev/fuse` を公開し、コンテナ内での追加の FUSE マウントを許可。既定は無効。`AGENTRUN_ALLOW_FUSE=1` でも有効化可能 |
| `--no-allow-fuse` | 環境変数で有効にしていても、その実行では FUSE を無効化 |
| `--secrets-file PATH` | `KEY=VALUE` 形式のファイルから環境変数を渡す。既定は `secrets/.env` があれば使用。`AGENTRUN_SECRETS_FILE` でも指定可能 |
| `--no-secrets` | 秘密情報の環境変数を渡さない |
| `--no-gh-broker` | `secrets/gh.env` に `GH_TOKEN` があっても GitHub 操作の仲介サービスを起動しない |
| `--reviewers LIST` | プロンプトに追記するレビュー担当の一覧 |
| `--target-diff PATH` | プロンプトに追記するレビュー対象の差分ファイル |
| `--target-report PATH` | プロンプトに追記するレビュー対象の報告書 |
| `--agents LIST` | プロンプトに追記するエージェントの一覧。複数起動の指定ではない |
| `--show-mounts` | `dry-run` でエージェント固有のマウントも表示 |
| `--submit` | 準備後に `sbatch` でジョブを投入 |
