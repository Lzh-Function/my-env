# Antigravity (agy) Configuration & Hooks Management Worklog

## 目標
1. `common/` 以下のファイル群（`hooks`, `skills`, `AGENTS.md`）が、Antigravity（agy）コンテナ内に適切に移行され反映される仕組みを構築する。
2. `common/` 側で追加・編集された hooks や skills などを、Antigravity 専用の設定ファイル（`agents/antigravity/hooks.json` 等）に反映させるための同期コマンド（`agentrun sync-antigravity`）を実装する。

## 現状の課題と分析
- 以前は `agents/antigravity/hooks.json` が手書きで管理されていた（あるいは `common/antigravity/` に実体があった）。そのため、`common/hooks/` に新しいスクリプトが追加された際、自動的に Antigravity 側に適用する仕組みがなかった。
- Claude Code 等では既に `hooks.manifest.json` を使ったメタデータの管理と、`agentrun sync-claude` コマンドによる JSON 生成が実装されていた。

## 実施した作業内容

### 1. `hooks.manifest.json` の導入
Claude Code の実装を参考に、Antigravity 側にも `agents/antigravity/hooks.manifest.json` を作成しました。
- このファイルは `event`（PreToolUse など）や `matcher`（Bash など）に、どの共通 Python スクリプト（`block_dangerous_command.py` 等）を紐付けるかを定義するメタデータです。
- Antigravity 特有の `"if": "Bash(git *)"` といった条件付きフックもこのマニフェスト内で管理可能になっています。

### 2. `agentrun sync-antigravity` の実装
`runtime/agentrun/agentrun` スクリプトを改修し、以下の機能を追加しました。
- **`render_antigravity_hooks_json`**: `hooks.manifest.json` をパースし、Antigravity CLI の仕様（パスのプレフィックスを `~/.gemini/antigravity-cli/hooks/` にする等）に合わせた `hooks.json` を jq を用いて自動生成します。
- **`command_sync_antigravity`**: `agentrun sync-antigravity` コマンドとして登録しました。これを実行すると、マニフェストから `hooks.json` が生成され、同時に `AGENTS.md`, `GEMINI.md`, `skills/` のシンボリックリンクが `common/` 側を参照するように張られます。

### 3. バリデーション機能の追加（`agentrun validate` への統合）
- **`validate_antigravity_hook_manifest`**: マニフェストファイルの構造が正しいか、未定義の共通フックスクリプトがないかなどを自動で検証するロジックを追加しました。
- **`validate_antigravity_sync`**: 生成済みの `hooks.json` がマニフェストと乖離していないか（Sync 漏れがないか）、シンボリックリンクが正しく張られているかをチェックするロジックを追加しました。
- これらの検証処理は、全体の `agentrun validate` にも組み込まれており、一括で整合性がテストされるようになっています。

### 4. コンテナへの反映機構の確認
`runtime/agentrun/agentrun` の `home_config_mounts()` において、以下のマウントが適切に動作していることを再確認しました。
- `~/.gemini/antigravity-cli/hooks/` への `common/hooks/` のディレクトリバインド
- `~/.gemini/antigravity-cli/skills/` へのバインド（シンボリックリンク経由で `common/skills/` に到達）
- `AGENTS.md`, `GEMINI.md` の読み込み
フックのスクリプト自体は `common/hooks/` が直接コンテナ内にバインドマウントされるため、**既存スクリプトの軽微な修正であれば `sync` コマンドを叩く必要すらなく即座にコンテナ内に反映されます。**（新規フックの追加・削除の時のみ `agentrun sync-antigravity` を叩けばよい設計です）。

### 5. 古いファイルの清掃
不適切に `common/antigravity/` 配下に置かれていた古い `hooks.json` などの非共有ファイルを削除し、管理を `agents/antigravity/` 以下へ一元化しました。

## 結果
`agentrun validate` および `agentrun sync-antigravity` のテストを実行し、すべての出力が `[OK]` となることを確認しました。
これにより、Antigravity (agy) は Claude Code や Codex と完全に同等レベルの共通設定・フック管理の仕組みを獲得しました。
