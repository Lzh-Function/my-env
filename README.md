# AI Agent Environment

Claude Code / Codex / Antigravity を Slurm compute node 上の Apptainer sandbox 内で実行するための設定・ランタイムリポジトリです。

詳細な利用手順は **[docs/USER_MANUAL.md](docs/USER_MANUAL.md)** を参照してください。

## ディレクトリ構成

```text
common/AGENTS.md          全 agent 共通ルール
agents/                   Claude, Codex, Antigravity 固有の設定・shim
profiles/                 assist / experiment / campaign / review / multi-review の runtime profile
runtime/agentrun/         login-node-safe agentrun shell launcher
runtime/apptainer/        Apptainer definition templates
tests/fixtures/           smoke-test goal ファイルおよびダミー repository
```

## Quick Start

### インストール

```bash
./install.sh          # dry-run（確認のみ）
./install.sh --apply  # $HOME/.local/bin/agentrun に symlink を作成
```

### Image ビルド（初回必須）

`.sif` は git 管理外のため、各ユーザーが compute node でビルドする必要があります。`runtime/apptainer/base-agent.sif` が存在しない場合、`doctor` は `[FAIL]` を出し、agent を起動できません。

```bash
runtime/apptainer/build-images.sh                                                   # dry-run（確認のみ）
srun --partition <partition> runtime/apptainer/build-images.sh --run                # 両方ビルド（必要な層だけ）
srun --partition <partition> runtime/apptainer/build-images.sh --run --force agent  # agent 層のみ強制再ビルド（agent CLI 更新時）
```

`base-system.sif` → `base-agent.sif` の順にビルドされます。ダウンロードを含むため数十分かかります。agent CLI のバージョンアップ時は `agent` を指定することで `base-system.sif` の再ビルドをスキップできます。完了後は `agentrun doctor --agent <name>` の `image:base-agent.sif` が `[OK]` になります。

### 認証情報のセットアップ（初回必須）

使用する agent CLI を host にインストールした後、`auth login` でログインと store へのインポートを一括実行します。

```bash
# 使用する agent ごとにログイン（ブラウザ / 対話認証）と store 登録をまとめて実行
agentrun auth login --agent claude
agentrun auth login --agent codex
agentrun auth login --agent antigravity   # agy 対話起動 → 認証後 /exit

# または全 agent を一括で
agentrun auth login --all
agentrun auth status
```

既に host 側でログイン済みの場合は `auth import` のみでも構いません。

```bash
agentrun auth import --agent claude
agentrun auth status --agent claude
```

### 動作確認

`doctor --agent NAME` は指定した agent の auth のみを検証します。`--all` は全 agent の auth を検証するため、使用しない agent のファイルが未設定だと FAIL になります。

```bash
agentrun validate
agentrun doctor --agent claude   # 使用する agent を指定する
```

### 実行例

```bash
# 対話式 assist（TTY が必要。PROMPT 不要 — agent 起動後にユーザーが指示を与える）
agentrun assist --agent codex --partition <partition>

# batch 投入（TTY 不要。PROMPT 必須）
agentrun assist --submit --agent codex --partition <partition> "Hello"

# dry-run（副作用なし、plan 表示のみ）
agentrun dry-run assist --agent codex --partition <partition> --show-mounts
```

`--partition` は環境変数 `AGENTRUN_SLURM_PARTITION` でも指定できます。

## コンテナ設定の仕組み

`agentrun` は run ごとに `.agent-runs/<run_id>/` を作成し、container 固有の config を生成してから bind-mount します。host `$HOME` は書き換えません。

## Image ビルド

Quick Start の「[Image ビルド（初回必須）](#image-ビルド初回必須)」を参照してください。

`build-images.sh` は `SLURM_JOB_ID` が設定されていない環境（login node）での実行を拒否します。`srun` または `sbatch` で compute node に投入してください。

```bash
runtime/apptainer/build-images.sh [--force] [system|agent]                                # dry-run
srun --partition <partition> runtime/apptainer/build-images.sh --run                      # 両方ビルド（必要な層だけ）
srun --partition <partition> runtime/apptainer/build-images.sh --run --force              # 両方を強制再ビルド
srun --partition <partition> runtime/apptainer/build-images.sh --run --force agent        # agent 層のみ強制再ビルド
```

`--force` なしでは、`.def`（agent 層は `base-system.sif` も）より古い `.sif` だけが作り直されます。agent CLI の更新など `.def` を変えずに作り直したいときは `--force` を付けてください。

## ドキュメント

| ドキュメント                                   | 内容                                                                         |
| ---------------------------------------------- | ---------------------------------------------------------------------------- |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md)     | コマンドリファレンス、run directory 構造、agent 差分、トラブルシューティング |
| [docs/operations-ja.md](docs/operations-ja.md) | 検証済みステータス、mount レイアウト、認証バインディング詳細                 |
