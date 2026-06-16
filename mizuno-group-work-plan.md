# mizuno-group AI Agent Runtime 作業計画

## Summary

- `plan.md` の設計を、既存の `mizuno-group/ai-agent-env/claude` 資産を起点に段階実装する。
- 初期ゴールは、Claude 既存運用を壊さず、Antigravity / Claude / Codex を Slurm + Apptainer capsule で起動できる最小基盤を作ること。
- `mizuno-group/ai-agent-env` を `ai-agent-config` 相当の設定正本として扱い、共通設定、agent 別 shim、runtime、検証コマンドを順に追加する。

## Key Changes

- `common/AGENTS.md`、agent 別 shim、profiles、hooks、skills、runtime、tests を追加する。
- 既存の Claude `CLAUDE.md` / `settings.json` / hooks / `work-log` skill は移行元として保持し、共通ルールと共通 hook 実体へ段階的に寄せる。
- `agentrun` を policy compiler として実装し、`validate`、`doctor`、`dry-run`、`assist`、`smoke-test`、`verify-run` を先に作る。
- `.agent-runs/<run_id>` と `latest` symlink を標準 run ledger にし、`live/` と `artifacts/` を実行中確認できる形で生成する。
- Apptainer image は `base-system.sif` と `base-agent.sif` の2層構成にし、uv と3社 agent CLI は image に入れ、認証情報は host 側から必要最小限だけ bind する。

## Implementation Phases

### Phase 0: 設定正本化

- `common/AGENTS.md` に HPC / Slurm / uv / Git / safety / observability / testing の共通ルールを集約する。
- Claude / Codex / Antigravity 用 shim と最小 settings/config 雛形を置く。
- auth、token、`.agent-runs/` を Git 管理しない `.gitignore` を整備する。

### Phase 1: 既存 Claude 資産の整理

- 既存 `claude/settings.json` と hooks の挙動を維持する。
- `deny-check.sh`、`login-node-guard.sh`、`python-env-guard.sh` のルールを共通 hook 候補として文書化する。
- `jq` など hook 実行依存を `doctor` の検査対象に入れる。

### Phase 2: runtime / image

- `runtime/apptainer/base-agent.def` を追加し、uv、Claude Code、Codex、Antigravity の install と PATH 整備を定義する。
- `runtime/agentrun` に adapter 構造を作り、Antigravity を default、Claude / Codex を secondary とする。
- auth bind と config read-only bind の mount plan を `dry-run` で確認可能にする。

### Phase 3: run ledger / observability

- `.agent-runs/<run_id>/live`、`artifacts`、`reviews`、`workspace`、`scratch`、`cache` を標準生成する。
- `stdout.log`、`stderr.log`、`status.json`、`heartbeat.txt`、`command_log.jsonl` を実行中に更新する。
- `agentrun status`、`logs --follow`、`list-runs` を追加する。

### Phase 4: assist から experiment へ拡張

- 最初に CPU `assist` を Slurm short job + Apptainer で動かす。
- 次に `experiment` で `goal.yaml`、`metrics.json`、`proposed_next.yaml`、GPU option を対応する。
- `review` / `multi-review` / `campaign` は assist と experiment の検証後に追加する。

## Test Plan

- `agentrun validate`: config、shim、profiles、hooks、skills、symlink、JSON/TOML/YAML 構文を検証する。
- `agentrun doctor --all`: Slurm、Apptainer、base image、uv、agent CLI、auth state、`.agent-runs` 書き込み可否を検証する。
- `agentrun dry-run`: Slurm command、Apptainer command、bind mount、capsule prompt、expected artifacts を表示する。
- `agentrun smoke-test --agent claude|codex|antigravity`: short CPU job で `report.md`、`metrics.json`、live logs、status を生成する。
- `agentrun verify-run .agent-runs/latest`: required outputs、JSON/JSONL parse、exit code、final status、Slurm job id を確認する。
- GPU smoke は `CLAUDE.md` の Slurm 指定に従い、Python 実行時は uv venv 選択ルールを満たしてから行う。

## Assumptions

- 出力ファイル名は `mizuno-group-work-plan.md` とする。
- `mizuno-group/ai-agent-env` を新規 `ai-agent-config` 相当の作業場所として扱う。
- 既存 Claude 設定は破壊せず、共通化は段階的に行う。
- Slurm / Apptainer の実実行は login node 直実行を避け、`CLAUDE.md` と既存 hook 方針に従う。
