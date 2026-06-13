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

### 認証情報のセットアップ（初回必須）

host 側の認証情報を agentrun の auth store にインポートします。

```bash
agentrun auth import --all
agentrun auth status
```

### 動作確認

```bash
agentrun validate
agentrun doctor --all
```

### 実行例

```bash
# 対話式 assist（TTY が必要）
agentrun assist --agent codex --partition <partition> "Hello"

# batch 投入（TTY 不要）
agentrun assist --submit --agent codex --partition <partition> "Hello"

# dry-run（副作用なし、plan 表示のみ）
agentrun dry-run assist --agent codex --partition <partition> --show-mounts "Hello"
```

`--partition` は環境変数 `AGENTRUN_SLURM_PARTITION` でも指定できます。

## コンテナ設定の仕組み

`agentrun` は run ごとに `.agent-runs/<run_id>/` を作成し、container 固有の config を生成してから bind-mount します。host `$HOME` は書き換えません。

login node 上で `claude` / `codex` / `agy` を直接使いたい場合のみ `./install.sh --apply` が必要です（container 経由の通常運用では不要）。

## Image ビルド

```bash
cd runtime/apptainer
./build-images.sh           # dry-run
./build-images.sh --run     # Slurm allocation 内で実際にビルド
```

## ドキュメント

| ドキュメント | 内容 |
|---|---|
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | コマンドリファレンス、run directory 構造、agent 差分、トラブルシューティング |
| [docs/operations-ja.md](docs/operations-ja.md) | 検証済みステータス、mount レイアウト、認証バインディング詳細 |
