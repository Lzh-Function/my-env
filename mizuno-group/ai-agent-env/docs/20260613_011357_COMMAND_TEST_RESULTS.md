# Command Test Results

**実施日時:** 2026-06-13 01:13:57  
**作業ディレクトリ:** `mizuno-group/ai-agent-env`  
**テスト対象:** `docs/USER_MANUAL.md` 掲載コマンド全体

---

## テスト結果サマリー

| 結果 | 件数 |
|---|---|
| PASS | 21 |
| PASS (既存成功 run を確認) | 3 |
| SKIP (auth 必須 / インタラクティブ) | 3 |
| **挙動不一致 (要注意)** | **2** |

---

## 共通コマンド

### `validate`

```
./runtime/agentrun/agentrun validate
```

**結果: PASS**  
全チェック OK、FAIL ゼロ。claude / codex / antigravity 三エージェント分の manifest 整合性、生成ファイル一致、symlink、hooks すべて通過。

---

### `agents`

```
./runtime/agentrun/agentrun agents
```

**結果: PASS**

```
Available agents:
  antigravity  primary   available /home/li/.local/bin/agy
  claude       secondary available /home/li/.local/bin/claude
  codex        secondary available /home/li/.local/bin/codex
```

---

### `list-runs`

```
./runtime/agentrun/agentrun list-runs
```

**結果: PASS**  
`.agent-runs/` 内のディレクトリが改行区切りでアルファベット順に列挙される。

---

### `status`

```
./runtime/agentrun/agentrun status
```

**結果: PASS (挙動は run の状態による)**  
最新 run (`latest` → `20260612_201541_assist-submit_codex`) の `live/status.json` が `{}` のため、出力は `{}` のみ。コマンド自体は正常動作。`status.json` が完成した run では `{"status":"success",...}` が返る。

---

### `logs`

```
./runtime/agentrun/agentrun logs
./runtime/agentrun/agentrun logs --follow
```

**結果: PASS (挙動は run の状態による)**  
`command_logs()` は `latest/live/slurm.out` を cat / tail -f する。最新 run を含む一部 run では `slurm.out` が空のため、出力が空になる。
- `slurm.out` は `#SBATCH --output=` で設定された SLURM ジョブ出力ファイル。sbatch 投入ジョブでは内容が書き込まれる。
- 成功済み run `20260611_015439_smoke-test_claude` でも `slurm.out` は空（`stdout.log` は非空）。

USER_MANUAL.md には「logs」の出力先が `stdout.log` か `slurm.out` か明記されていないが、実装は `slurm.out` のみ。

---

### `tail`

```
./runtime/agentrun/agentrun tail
```

**結果: PASS**  
`tail` は `logs --follow` の alias（`tail -f` を実行）。最新 run の `slurm.out` が空のため follow 中は出力なし。follow モードのためテストは数秒で終了させた。

---

### `open-run`

```
./runtime/agentrun/agentrun open-run .agent-runs/latest
```

**結果: PASS**  
symlink を `readlink -f` で解決して絶対パスを返す。

---

### `verify-run`（成功 run）

```
./runtime/agentrun/agentrun verify-run .agent-runs/20260611_015439_smoke-test_claude
```

**結果: PASS**

```
[OK] run directory: .agent-runs/20260611_015439_smoke-test_claude
[OK] capsule.yaml
[OK] prompt.txt
[OK] goal.yaml
[OK] live/status.json
...（全チェック OK）
[OK] final_status:success
[OK] exit_code
[OK] slurm_job_id
```

---

### `verify-run`（最新の不完全 run）

```
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

**結果: コマンドは正常動作、run が不完全なため失敗を検出**  
`live/status.json` が `{}` (空)、`artifacts/report.md` が欠如しているため複数の `[FAIL]` を報告。コマンドの動作自体は正常。

---

## claude コマンド

### `doctor --agent claude`

```
./runtime/agentrun/agentrun doctor --agent claude
```

**結果: PASS**  
srun/sbatch/apptainer のパス確認、SIF ファイル、claude CLI 存在確認がすべて通過。auth ファイル (`$HOME/.claude/.credentials.json`, `$HOME/.claude.json`) の有無も報告。

---

### `dry-run assist --agent claude --show-mounts`

```
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator --show-mounts "Hello"
```

**結果: PASS（コマンド実行は正常）**  
srun + Apptainer コマンドが表示される。bind_mounts に `agents/claude/CLAUDE.md:/home/sandbox/.claude/CLAUDE.md:ro`、`common/hooks:/home/sandbox/.claude/hooks:ro` が含まれることを確認。

**⚠️ 挙動不一致 1 (後述)**

---

### `sync-claude`

```
./runtime/agentrun/agentrun sync-claude
```

**結果: PASS**

```
[OK] synced agents/claude/settings.json hooks from agents/claude/hooks.manifest.json
[OK] synced agents/claude/CLAUDE.md -> ../../common/AGENTS.md
[OK] synced agents/claude/skills -> ../../common/skills
```

idempotent 確認済み（2回実行しても validate が FAIL にならない）。

---

### `assist-pty` smoke test

```
tests/slurm/submit_creator_tests.sh assist-pty
```

**結果: PASS（既存 run 確認）**  
`.agent-runs/assist-pty-smoke/status.json` に `{"status":"success","test":"assist-pty-smoke"}` が存在。  
確認内容:
- `write_plan` が正しいインタラクティブコマンドを生成する
- CLAUDE.md bind-mount が `agents/claude/CLAUDE.md`（symlink）を使う
- コンテナ起動 + `claude --version` 成功

---

## codex コマンド

### `doctor --agent codex`

```
./runtime/agentrun/agentrun doctor --agent codex
```

**結果: PASS**  
必要ツール、SIF、codex CLI を確認。auth ファイル (`$HOME/.codex/auth.json`) の有無も報告。

---

### `dry-run assist --agent codex --show-mounts`

```
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator --show-mounts "Hello"
```

**結果: PASS**  
bind_mounts に `agents/codex/requirements.toml:/etc/codex/requirements.toml:ro`、`agents/codex/AGENTS.md:/home/sandbox/.codex/AGENTS.md:ro` 等が含まれることを確認。

---

### `sync-codex`

```
./runtime/agentrun/agentrun sync-codex
```

**結果: PASS**  
`agents/codex/hooks.json`、`agents/codex/requirements.toml` を再生成。AGENTS.md symlink、skills symlink を更新。

---

### `codex-assist-pty` smoke test

```
tests/slurm/submit_creator_tests.sh codex-assist-pty
```

**結果: PASS（既存 run 確認）**  
`.agent-runs/codex-assist-pty-smoke/status.json` に `{"status":"success","test":"codex-assist-pty-smoke"}` が存在。  
確認内容:
- interactive assist が top-level `codex` を使う
- submitted assist が `codex exec` を使う
- Codex config が run home 内で writable
- `/etc/codex/requirements.toml`、AGENTS.md、rules、common skills が可視

---

### `codex-auth` smoke test

```
tests/slurm/submit_creator_tests.sh codex-auth
```

**結果: PASS（最新 run: 20260612_201537_codex_auth_smoke、SLURM job 3537）**

```
{"status":"success","agent":"codex","mode":"auth-smoke","job_id":"3537"}
```

確認内容:
- `codex exec` がコンテナ内で実行できる
- shell command が実行できる
- managed hooks が発火する
- `PostToolUse` が command を `/runs/live/command_log.jsonl` に記録する

---

## antigravity コマンド

### `doctor --agent antigravity`

```
./runtime/agentrun/agentrun doctor --agent antigravity
```

**結果: PASS**  
必要ツール、SIF、antigravity CLI (`agy`) を確認。

---

### `dry-run assist --agent antigravity --show-mounts`

```
./runtime/agentrun/agentrun dry-run assist --agent antigravity --partition small-creator --show-mounts "Hello"
```

**結果: PASS（コマンド実行は正常）**  
bind_mounts を出力。hooks が `/home/sandbox/.gemini/antigravity-cli/hooks:ro` に mount されることを確認。

**⚠️ 挙動不一致 2 (後述)**

---

### `sync-antigravity`

```
./runtime/agentrun/agentrun sync-antigravity
```

**結果: PASS**  
`agents/antigravity/hooks.json` 再生成、symlinks を更新。

---

### `assist`（インタラクティブ）、`assist --submit`、`experiment` — antigravity / claude / codex

```
./runtime/agentrun/agentrun assist --agent <agent> --partition small-creator "Hello"
./runtime/agentrun/agentrun assist --submit --agent <agent> --partition small-creator "Hello"
./runtime/agentrun/agentrun experiment --agent <agent> --partition small-creator --goal ... "Hello"
```

**結果: SKIP**  
- インタラクティブ `assist` は `srun --pty` を必要とし、TTY なし環境ではテスト不可。
- `assist --submit` / `experiment` は実際のエージェント実行を伴い、有効な auth credentials が必要。
- 既存の成功 run（例: `20260611_015439_smoke-test_claude` status: success、`20260611_165605_assist_codex` 等）が存在し、コマンド自体は実績がある。

---

## 挙動不一致 (Bug Report)

### 不一致 1: `dry-run` が run directory を作成しない

**USER_MANUAL.md の記述（claude 章・codex 章・antigravity 章、共通）:**

> `run directory を作成し、... 予定される Slurm command と Apptainer command を表示します。`

**実際の挙動:**

`dry-run` 実行前後で `.agent-runs/` 内のディレクトリ数は変化しない。`host_run_directory` の値は表示されるが、ディレクトリは **作成されない**。

**確認方法:**
```bash
ls .agent-runs/ | wc -l           # 前: 55
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator "test"
ls .agent-runs/ | wc -l           # 後: 55 (変化なし)
ls .agent-runs/ | grep 20260613   # 空 (新規ディレクトリなし)
```

**影響:** 「dry-run でディレクトリを確認できる」という期待が持てないが、実用上は dry-run に run directory は不要であり、機能的な問題はない。ドキュメントの記述が実装と乖離している。

---

### 不一致 2: antigravity の `settings.json` が bind-mount されている（ドキュメントには記載なし）

**USER_MANUAL.md の記述（antigravity 章、Mount 構成セクション）:**

> 設定ファイル `settings.json` は書き込みエラー（read-only file system）を防ぐため、バインドマウントではなく `<run_dir>/home/.gemini/antigravity-cli/settings.json` に **コピー** されて配置されます。

また、Mount 構成の表に `settings.json` は列挙されていない。

**実際の挙動:**

`home_config_mounts()` 関数 (agentrun L.379-388) が `settings.json` を `/home/sandbox/.gemini/settings.json:ro` に **bind-mount** している。これは `dry-run --show-mounts` で確認できる。

```
--bind .../agents/antigravity/settings.json:/home/sandbox/.gemini/settings.json:ro
```

実際の run では **加えて** `stage_auth()` (agentrun L.286-287) が `container_config/settings.json` を `<run_dir>/home/.gemini/antigravity-cli/settings.json` にコピーする。

| | USER_MANUAL.md の記述 | 実際の挙動 |
|---|---|---|
| bind-mount の有無 | なし（コピーのみ） | あり（`/home/sandbox/.gemini/settings.json:ro`） |
| コピーの有無 | あり（`<run_dir>/home/.gemini/antigravity-cli/settings.json`） | あり（同パス） |
| コンテナ内パス | `/home/sandbox/.gemini/antigravity-cli/settings.json` のみ | 上記に加え `/home/sandbox/.gemini/settings.json` も存在 |

**影響:** `settings.json` がコンテナ内の2か所に配置される。Antigravity CLI が参照するパスが `/home/sandbox/.gemini/antigravity-cli/settings.json` であれば機能的問題はないが、bind-mount 先の `/home/sandbox/.gemini/settings.json` は意図しないパスにも見える。

---

## テスト対象外

| コマンド | 理由 |
|---|---|
| `assist --agent * --partition *` (インタラクティブ) | srun --pty はインタラクティブ TTY が必要 |
| `assist --submit --agent *` (新規投入) | 有効な API auth 必要、SLURM job 実行時間が必要 |
| `experiment --agent *` | 同上 |
| `install.sh` / `doctor.sh` | ユーザー環境依存、インストール系は範囲外 |
