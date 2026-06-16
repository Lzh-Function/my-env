# 理念
- エージェント群をapptainerのsifファイル内に隔離
- ログインノードからジョブを投げて、計算ノードのさらにapptainerの内部でエージェントが自由に動けるようにする
- 全てのファイル操作が無承認で動くようにする。
- srunとsbatchの両方が使える形式としたい（補助コーディングの場合はsrunで隔離環境にいるエージェントと対話、/goalを用いた自律実験の場合はsbatchで自由に働いてもらう）
  - srunでは、ユーザーが`srun...`と長々と打つことなく規定のパーティションやエージェント種などを設定後はコマンドで走る形式としたい。「ログインノードのターミナルでコマンドを打つ→そのターミナルで計算ノードで起動したコンテナ内のエージェントと対話できる」という形式にしたい。
  - sbatchでは、基本的に自律実験レベルのことをやらせる際に利用し、基本は/goalを利用し、goal.yamlや他プロンプトを渡してコーディングや実験を実行してもらう形式にしたい。

# エージェントのログイン・各種設定・skillsやhook
- ログインノード側での$HOME/.codex/, $HOME/.claude/, $HOME/.gemini(/.antigravity-cli/)に認証情報あり
- `ai-agent-env`の`common`でAGENTS.mdやCLAUDE.md、hooksや一元管理、各エージェントのホーム直下ディレクトリにsymlinkを張って変更同期。各エージェント特有のものは`common`と同階層にある`agents`直下で個別対応。
- **コンテナ内で認証情報をバインドマウントしてログインがコンテナ内で正常に行われるようにしたいが、各種設定のsymlinkを張るときに大本のホスト側（ログインノード）の$HOME/...が変わることは避けたい（要検討事項）**
  - 現在の非常に苦しい状況：エージェントのログイン認証情報はログインノードの各ユーザー$HOME直下にのみ存在、これを「→計算ノード→コンテナ内」と二段階で運ばないといけない

  **[実装済み 2026-06-11 by Claude Code]** 以下の方式で解決：
  - `agentrun` submit 時（ログインノード上）に `$HOME/.claude/.credentials.json` と `$HOME/.claude.json` を `$run_dir/home/.claude/` にコピー
  - 既存の `--home $run_dir/home:/home/sandbox` マウントでコンテナ内 `/home/sandbox/` に自動的に届く
  - `--bind $HOME/.claude:/home/sandbox/.claude:rw` は廃止（compute node が `/home/li` を見えないため FATAL になっていた）
  - セキュリティ上、ジョブ終了時に `submit.sbatch` の `trap _cleanup_auth EXIT` で `.credentials.json` と `.claude.json` を自動削除
  - 変更ファイル: `runtime/agentrun/agentrun`、`runtime/agentrun/agentrun.py`、`runtime/agentrun/adapters/claude.py`

# 無承認かつ非対話式で動かす方法
1. プロンプト、小規模プロジェクト（補助コーディング等）
| CLI             | 非対話式          | 無承認/承認スキップ                                                            | sbatch向けコマンド                                            |
| --------------- | ----------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------- |
| Codex CLI       | `codex exec`      | `--ask-for-approval never` または `--dangerously-bypass-approvals-and-sandbox` | `codex exec --dangerously-bypass-approvals-and-sandbox "..."` |
| Antigravity CLI | `agy -p "..."`    | `--dangerously-skip-permissions`                                               | `agy -p --dangerously-skip-permissions "..."`                 |
| Claude Code CLI | `claude -p "..."` | `--dangerously-skip-permissions` / `--permission-mode bypassPermissions`       | `claude -p --dangerously-skip-permissions "..."`              |
2. /goalの利用（自律実験、完全に自主的にrun）
Claude Code:
   claude -p --dangerously-skip-permissions --max-turns N (設定してもしなくてもよい) "/goal ..."
Codex:
   codex exec --dangerously-bypass-approvals-and-sandbox "/goal ..."
Antigravity:
   agy -p --dangerously-skip-permissions "/goal"