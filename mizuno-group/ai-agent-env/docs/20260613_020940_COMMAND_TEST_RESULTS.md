# Command Test Results

**実施日時:** 2026-06-13 02:09:40 JST  
**作業ディレクトリ:** `/workspace/filesrv01/li/02_work/slurm-agents-capsule/mizuno-group/ai-agent-env`  
**対象:** `docs/USER_MANUAL.md` と `./runtime/agentrun/agentrun` の整合性再確認  

## Summary

| 区分 | 結果 |
|---|---|
| syntax | PASS |
| validate / sync | PASS |
| doctor auth check | PASS |
| dry-run | PASS |
| Slurm smoke | PASS |
| Antigravity submit | PASS |
| known limitation | `review` / `multi-review` / `campaign` は orchestrator 未実装として USER_MANUAL.md に明記 |

## 実装修正の確認

### `doctor --agent *` auth check

`doctor` に agent 別 auth check が追加され、以下を確認するようになった。

```text
claude:      $HOME/.claude/.credentials.json または $HOME/.claude.json
codex:       $HOME/.codex/auth.json
antigravity: $HOME/.gemini/antigravity-cli/antigravity-oauth-token または installation_id
```

確認コマンド:

```bash
./runtime/agentrun/agentrun doctor --agent claude
./runtime/agentrun/agentrun doctor --agent codex
./runtime/agentrun/agentrun doctor --agent antigravity
./runtime/agentrun/agentrun doctor --all
```

結果:

- `doctor --agent claude`: exit 0, `[OK] auth:claude`
- `doctor --agent codex`: exit 0, `[OK] auth:codex`
- `doctor --agent antigravity`: exit 0, `[OK] auth:antigravity`
- `doctor --all`: exit 0, 3 agent すべての auth check を表示

`apptainer` と `uv` は login host 上では not found のため WARN。これは USER_MANUAL.md に記載済み。

## Login-node Tests

### syntax

```bash
bash -n runtime/agentrun/agentrun
python3 -m py_compile runtime/agentrun/agentrun.py
```

結果: PASS

### validate / sync

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun sync-antigravity
./runtime/agentrun/agentrun validate
```

結果: PASS

確認内容:

- required paths OK
- JSON/TOML shape OK
- hook executable bit OK
- Claude / Codex / Antigravity manifest and generated config OK
- symlink OK

### agents

```bash
./runtime/agentrun/agentrun agents
```

結果: PASS

```text
Available agents:
  antigravity  primary   available /home/li/.local/bin/agy
  claude       secondary available /home/li/.local/bin/claude
  codex        secondary available /home/li/.local/bin/codex
```

### dry-run assist

```bash
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator --show-mounts "Hello"
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator --show-mounts "Hello"
./runtime/agentrun/agentrun dry-run assist --agent antigravity --partition small-creator --show-mounts "Hello"
```

結果: PASS

確認内容:

- Claude: `srun --pty` と interactive `claude` command を表示。
- Codex: `srun --pty` と top-level interactive `codex` command を表示。
- Antigravity: `srun --pty` と interactive `agy` fallback command を表示。
- `dry-run` は `host_run_directory` を表示するが、実 directory は作成しない。USER_MANUAL.md に反映済み。

Antigravity について、前回問題だった `/home/sandbox/.gemini/settings.json:ro` bind は dry-run 出力に存在しない。

### dry-run experiment

```bash
./runtime/agentrun/agentrun dry-run experiment --submit --agent codex --partition small-creator --goal tests/fixtures/goal_smoke.yaml --repo . "Run the goal"
```

結果: PASS

確認内容:

- `launch_method: sbatch`
- `sbatch_args` に `--partition=small-creator`, `--time=04:00:00`, `--mem=64000M`, `--cpus-per-task=8`
- command は non-interactive `codex exec`

USER_MANUAL.md の experiment 例は `--submit` 付きに更新済み。

### dry-run multi-review

```bash
./runtime/agentrun/agentrun dry-run multi-review --agent codex --agents claude,codex,antigravity --partition small-creator "review test"
```

結果: PASS as scaffold / limitation confirmed

確認内容:

- 起動される agent は `--agent codex` の 1 つだけ。
- `--agents claude,codex,antigravity` は prompt の `Requested agents:` に追記されるだけ。
- 複数 `sbatch`、相互レビュー、結果集約は行われない。

USER_MANUAL.md に「orchestrator 未実装」として反映済み。

### run確認系

```bash
./runtime/agentrun/agentrun status
./runtime/agentrun/agentrun logs
timeout 3 ./runtime/agentrun/agentrun logs --follow
timeout 3 ./runtime/agentrun/agentrun tail
./runtime/agentrun/agentrun list-runs
./runtime/agentrun/agentrun open-run .agent-runs/latest
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

結果:

- `status`: exit 0。実行時点の latest が prepared/incomplete run のため `{}`。
- `logs`: exit 0。実行時点の latest stdout が空のため出力なし。
- `logs --follow`: timeout exit 124。follow 起動自体は正常。
- `tail`: timeout exit 124。follow 起動自体は正常。
- `list-runs`: exit 0。
- `open-run`: exit 0。
- `verify-run .agent-runs/latest`: exit 1。latest が不完全 run を指していたため、`artifacts/report.md` と `final_status` の FAIL を正しく検出。

USER_MANUAL.md には、`status` / `logs` / `tail` が `.agent-runs/latest` 依存であること、`latest` が未完了 run の場合は `{}` になり得ることを記載済み。

## Slurm Tests

### Smoke helpers

```bash
tests/slurm/submit_creator_tests.sh assist-pty
tests/slurm/submit_creator_tests.sh codex-assist-pty
tests/slurm/submit_creator_tests.sh codex-auth
```

結果:

| job | command | state | exit |
|---:|---|---|---|
| 3587 | `assist-pty` | COMPLETED | 0:0 |
| 3588 | `codex-assist-pty` | COMPLETED | 0:0 |
| 3589 | `codex-auth` | COMPLETED | 0:0 |

Status:

```text
.agent-runs/assist-pty-smoke/status.json
{"status":"success","test":"assist-pty-smoke"}

.agent-runs/codex-assist-pty-smoke/status.json
{"status":"success","test":"codex-assist-pty-smoke"}

.agent-runs/creator-codex-auth-smoke/20260613_020657_codex_auth_smoke/live/status.json
{"status":"success","agent":"codex","mode":"auth-smoke","job_id":"3589"}
```

### Antigravity submit

```bash
./runtime/agentrun/agentrun assist --submit --agent antigravity --partition small-creator --repo . "Command test: reply OK and write a short report to /runs/artifacts/report.md. Do not edit repository files."
```

結果: PASS

- prepared run: `.agent-runs/20260613_020657_assist_antigravity`
- Slurm job: `3590`
- `sacct`: `COMPLETED`, `ExitCode=0:0`, elapsed `00:01:35`
- `live/status.json`: `{"status":"success","agent":"antigravity","mode":"assist","job_id":"3590"}`
- `live/exit_code.txt`: `0`
- `artifacts/report.md`: non-empty, 608 bytes
- `verify-run .agent-runs/20260613_020657_assist_antigravity`: exit 0
- job 完了後、`<run_dir>/home` は削除済み

Antigravity mount 確認:

```bash
grep -F '/home/sandbox/.gemini/settings.json' .agent-runs/20260613_020657_assist_antigravity/apptainer_exec.sh
```

結果: no match。古い read-only settings bind は存在しない。

## USER_MANUAL.md 更新確認

反映した内容:

- `doctor` が auth file を確認することを明記。
- agent 別 auth path を共通セクションに明記。
- `dry-run` は `host_run_directory` を表示するだけで directory を作らないことを明記。
- `review` / `multi-review` / `campaign` は orchestrator 未実装であり、単一起動 scaffold であることを明記。
- Codex 章の「他 agent が後から追記予定」という古い注記を削除。
- Claude の run-home auth 確認例を `.agent-runs/latest/home/...` から `.agent-runs/<run_id>/home/...` に変更し、cleanup 後は消えることを明記。
- Codex auth smoke の確認例を glob 全件表示から latest run directory 絞り込みに変更。
- Antigravity の `settings.json` は bind mount ではなく run home に copy される構成として維持。

## Remaining Notes

- `verify-run .agent-runs/latest` は latest が不完全 run を指すと失敗する。これは検出として正常。
- Claude / Codex の任意 prompt による `assist --submit` は、agent が `/runs/artifacts/report.md` を作らない場合 `verify-run` が失敗し得る。今回の再テストでは Antigravity submit のみ report 生成まで実確認した。
- `review` / `multi-review` / `campaign` はまだ自動 orchestration 機能ではない。
