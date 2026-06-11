# AI Agent Runtime 運用メモ

この文書は、`plan.md` の設計に対して現在のリポジトリがどこまで実装・検証済みか、実運用時にどのような Slurm / Apptainer / mount / 認証構成になるかを説明する。

## 現在の到達点

現時点では、ログインノードから `agentrun` で Slurm job 用の run directory と submit script を生成し、計算ノード上で Apptainer container を起動するための基盤が入っている。

運用可能な範囲:

- `agentrun validate` による設定ファイル、profile、hook、JSON/TOML 形状、symlink の静的検査。
- `agentrun doctor --all` による Slurm CLI、agent CLI、image、run directory、Git 状態の確認。
- `agentrun dry-run <mode>` による Slurm command、Apptainer command、bind mount、prompt、期待成果物の確認。
- `agentrun assist|experiment|campaign|review|multi-review ...` による `.agent-runs/<run_id>/` の作成と `submit.sbatch` の生成。
- `--submit` 指定時の `sbatch` 投稿。
- `agentrun smoke-test --submit` と `agentrun verify-run` による Slurm 上の live ledger / artifact 生成確認。
- `tests/slurm/submit_creator_tests.sh build` による SIF 作成。
- `tests/slurm/submit_creator_tests.sh agents` による container 内 agent CLI 起動確認。
- `tests/slurm/submit_creator_tests.sh codex-auth` による Codex 認証情報 staging と `codex exec` の簡易実行確認。

検証済みの結果:

- `runtime/apptainer/base-system.sif` 作成済み。
- `runtime/apptainer/base-agent.sif` 作成済み。
- Slurm job array `3305` で Antigravity (`agy`)、Codex、Claude の CLI 起動 smoke が成功。
- Slurm job `3309` で `agentrun smoke-test --submit` が成功し、`verify-run .agent-runs/latest` が成功。
- Slurm job `3395` で Codex 認証情報を run home に stage し、`codex exec` が `OK_CODEX_AUTH_SMOKE` を返すことを確認。job 終了後、staged `auth.json` は削除済み。

未完了または制約が残る範囲:

- Python 実装 `runtime/agentrun/agentrun.py` は、AGENTS.md の uv venv 選択ルールを満たす環境が未選択のため未検証。
- 実 agent による長時間の `assist` / `experiment` / `campaign` / `review` / `multi-review` は、submit script 生成までは実装済みだが、workflow ごとの実運用検証はこれから。
- `tests/slurm/agent-cli-smoke.sbatch` は「CLI が container 内で起動できること」の確認であり、認証済みモデル応答の確認ではない。Codex の認証済み応答確認は `codex-auth` smoke で行う。

## ディレクトリ構成

重要なパスは以下。

```text
common/                  全 agent 共通ルール、hooks、共通 skills
agents/claude/           Claude Code 用 shim、settings、skills
agents/codex/            Codex 用 AGENTS.md、config.toml、hooks、rules
agents/antigravity/      Antigravity/Gemini 系 shim、settings、rules
profiles/                assist / experiment / campaign / review / multi-review の profile
runtime/agentrun/        agentrun launcher と Python runtime modules
runtime/apptainer/       Apptainer definition と SIF build script
tests/slurm/             creator partition 用の cluster test scripts
.agent-runs/             run ledger、live logs、artifacts
```

`mizuno-group/ai-agent-env` は、container 内では `/home/sandbox/ai-agent-config` として read-only mount される。これが設定正本であり、認証情報はここには置かない。

## 実行の流れ

基本の流れは以下。

1. ログインノードで `agentrun` を実行する。
2. `agentrun` が `.agent-runs/<run_id>/` を作成する。
3. `prompt.txt`、`goal.yaml`、`capsule.yaml`、`apptainer_exec.sh`、`submit.sbatch` を生成する。
4. `--submit` があれば `sbatch .agent-runs/<run_id>/submit.sbatch` を実行する。
5. Slurm job が計算ノード上で `apptainer_exec.sh` を実行する。
6. container 内 agent が `/workspace`、`/runs`、`/scratch`、`/cache` を見ながら動く。
7. 実行中ログと成果物は host 側 `.agent-runs/<run_id>/` から確認できる。

product runtime script には cluster 固有 partition 名を埋め込まない。partition が必要な環境では、以下のどちらかで指定する。

```bash
./runtime/agentrun/agentrun assist --partition small-creator --agent claude --repo . "..."
AGENTRUN_SLURM_PARTITION=small-creator ./runtime/agentrun/agentrun assist --agent claude --repo . "..."
```

`small-creator` などの creator partition 名は test script 内だけで使う。

## Apptainer image

SIF は 2 層構成。

```text
runtime/apptainer/base-system.sif
runtime/apptainer/base-agent.sif
```

`base-system.sif` は CUDA Ubuntu base と基本ツールを含む。

`base-agent.sif` は以下を含む。

- `uv` / `uvx`
- Claude Code CLI
- Codex CLI
- Antigravity CLI (`agy`)
- PATH 整備用の `/etc/profile.d/sandbox-env.sh`
- `/usr/local/bin` への CLI symlink

build script は以下。

```bash
cd runtime/apptainer
./build-images.sh
./build-images.sh --run
```

`./build-images.sh` は dry-run がデフォルト。`--run` は Slurm allocation 内でのみ実行できる。

NFS 負荷対策として、現在の build は repository 配下に `APPTAINER_CACHEDIR` や `APPTAINER_TMPDIR` を設定しない。`apptainer build --disable-cache` を使い、既存 SIF が definition より新しい場合は再利用する。

重要: 既存の `.agent-runs/apptainer-cache` や `.agent-runs/apptainer-tmp` が残っていても、NFS 負荷を避けるため `rm -rf` で削除しない。必要なら使わずに放置するか、管理者判断で低負荷な方法で整理する。

## Mount 方式

`agentrun` が生成する Apptainer command は、概ね以下の形になる。

```bash
apptainer exec \
  --containall \
  --cleanenv \
  --home <run_dir>/home:/home/sandbox \
  --bind <run_dir>/workspace:/workspace:rw \
  --bind <run_dir>:/runs:rw \
  --bind <run_dir>/scratch:/scratch:rw \
  --bind <run_dir>/cache:/cache:rw \
  --bind <repo>/mizuno-group/ai-agent-env:/home/sandbox/ai-agent-config:ro \
  <agent-specific staged auth or auth binds> \
  <agent-specific config binds> \
  runtime/apptainer/base-agent.sif \
  bash -l -c '<agent command>'
```

標準 mount:

| Host 側 | Container 側 | 権限 | 用途 |
| --- | --- | --- | --- |
| `.agent-runs/<run_id>/home` | `/home/sandbox` | rw | agent の HOME。実行ごとに分離 |
| `.agent-runs/<run_id>/workspace` | `/workspace` | rw | agent が作業する workspace |
| `.agent-runs/<run_id>` | `/runs` | rw | live logs、artifacts、prompt、metadata |
| `.agent-runs/<run_id>/scratch` | `/scratch` | rw | 一時作業領域 |
| `.agent-runs/<run_id>/cache` | `/cache` | rw | run 単位の cache |
| repo の `ai-agent-env` | `/home/sandbox/ai-agent-config` | ro | 設定正本 |

GPU 指定時は `--gpus N` に応じて `apptainer exec --nv` と `#SBATCH --gres=gpu:N` が付く。

## workspace 側の変更確認

現在の標準 mount では、container 内 `/workspace` は host 側 `.agent-runs/<run_id>/workspace` に対応する。つまり、agent が `/workspace` に作ったファイルや変更は、host では以下に現れる。

```text
.agent-runs/<run_id>/workspace/
```

元の checkout そのものを直接 `/workspace` に rw mount する構成ではない。これは、agent の試行錯誤を run directory 内に閉じ込め、元 repo への影響を明示的に制御するための設計である。

run の確認に使う主な場所:

```text
.agent-runs/latest                         最新 run への symlink
.agent-runs/<run_id>/live/stdout.log       agent 標準出力
.agent-runs/<run_id>/live/stderr.log       agent 標準エラー
.agent-runs/<run_id>/live/status.json      実行状態
.agent-runs/<run_id>/live/heartbeat.txt    heartbeat
.agent-runs/<run_id>/live/current_task.md  現在タスク
.agent-runs/<run_id>/artifacts/report.md   最終報告
.agent-runs/<run_id>/artifacts/git_diff.patch  差分
.agent-runs/<run_id>/artifacts/metrics.json     metrics
.agent-runs/<run_id>/reviews/              review mode の出力
```

確認コマンド例:

```bash
./runtime/agentrun/agentrun status
./runtime/agentrun/agentrun logs --follow
./runtime/agentrun/agentrun tail
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

元 repo に変更を取り込む場合は、run directory 内の `workspace` や `artifacts/git_diff.patch` を確認してから、人間または別の明示的な手順で反映する。

## 認証情報の立て付け

認証情報は image に焼き込まない。host 側でログイン済みの情報を、agent ごとに必要最小限だけ container の `/home/sandbox` へ bind mount する。

**コンテナ実行では `install.sh --apply` は不要。** `agentrun` が run directory 準備時に
`.agent-runs/<run_id>/container_config/` 下に run 固有の config ファイル（CLAUDE.md、settings.json）を
自動生成し、それを bind mount する。ホスト側 `$HOME` は一切変更しない。

`install.sh --apply` が必要なのは、ログインノード上で `claude` / `agy` / `codex` を container 外で
直接実行する場合のみ。その場合、`$HOME/.claude/CLAUDE.md` はシンボリックリンクではなく、
ホスト絶対パスで `@`-import を解決した生成ファイルとして配置される。

### Bind mount の順序（Claude の例）

```
1. auth bind（先）:
   $HOME/.claude:/home/sandbox/.claude:rw   ← auth state 全体

2. config override bind（後）:
   <run_dir>/container_config/CLAUDE.md:/home/sandbox/.claude/CLAUDE.md:ro
   <run_dir>/container_config/settings.json:/home/sandbox/.claude/settings.json:ro
   ai-agent-env/common/hooks:/home/sandbox/.claude/hooks:ro
   ai-agent-env/agents/claude/skills:/home/sandbox/.claude/skills:ro
```

Apptainer では後発 bind が同一 container パスの先発 bind を上書きする。
これにより、`install.sh --apply` 実行済みか否かにかかわらず、コンテナ内の config は
常に run 固有の生成ファイルから供給される。

### container_config の生成内容

`agentrun` は `write_plan()` 内で以下を生成する。

**`container_config/CLAUDE.md`**: `agents/claude/CLAUDE.md` の `@`-import を
コンテナ内絶対パスに書き換えたもの。

```text
@../../common/AGENTS.md  →  @/home/sandbox/ai-agent-config/common/AGENTS.md
@../../claude/CLAUDE.md  →  @/home/sandbox/ai-agent-config/claude/CLAUDE.md
```

**`container_config/settings.json`**: モード別に以下を選択してコピー。

| mode | 使用する settings ファイル |
| --- | --- |
| `assist` | `settings.assist.json` → fallback: `settings.json` |
| `experiment` | `settings.experiment.json` → fallback: `settings.json` |
| その他 | `settings.json` |

### Agent ごとの auth bind

Claude:

| Host 側 | Container 側 | 権限 |
| --- | --- | --- |
| `$HOME/.claude` | `/home/sandbox/.claude` | rw |
| `$HOME/.claude.json` | `/home/sandbox/.claude.json` | rw |

Codex:

| Host 側 | Container 側 | 権限 |
| --- | --- | --- |
| `$HOME/.codex/auth.json` を `--submit` 時に `.agent-runs/<run_id>/home/.codex/auth.json` へコピー | `/home/sandbox/.codex/auth.json` | rw |

Antigravity:

| Host 側 | Container 側 | 権限 |
| --- | --- | --- |
| `$HOME/.gemini` | `/home/sandbox/.gemini` | rw |
| `$HOME/.antigravity` | `/home/sandbox/.antigravity` | rw |

### Config bind の参照元

Claude config（config override として auth bind の後段に追加）:

```text
<run_dir>/container_config/CLAUDE.md    -> /home/sandbox/.claude/CLAUDE.md    (ro)
<run_dir>/container_config/settings.json-> /home/sandbox/.claude/settings.json (ro)
common/hooks                            -> /home/sandbox/.claude/hooks          (ro)
agents/claude/skills                    -> /home/sandbox/.claude/skills         (ro)
```

Codex config:

```text
<run_dir>/home/.codex/config.toml     -> /home/sandbox/.codex/config.toml (rw, --home 経由)
agents/codex/hooks.json                -> /home/sandbox/.codex/hooks.json  (ro)
agents/codex/AGENTS.md                 -> /home/sandbox/.codex/AGENTS.md   (ro)
agents/codex/rules                     -> /home/sandbox/.codex/rules       (ro)
common/skills/<name>                   -> /home/sandbox/.codex/skills/<name> (run home 内 symlink)
```

`home/.codex/config.toml` は mode 別に以下をコピーして生成する。Codex TUI は
workspace trust などを `~/.codex/config.toml` に永続化しようとするため、このファイルは
read-only bind mount ではなく run home 内の writable copy として配置する。

| mode | 使用する Codex config |
| --- | --- |
| `assist` | `agents/codex/config.assist.toml` → fallback: `config.toml` |
| `experiment` | `agents/codex/config.experiment.toml` → fallback: `config.toml` |
| その他 | `agents/codex/config.toml` |

Antigravity config:

```text
agents/antigravity/settings.json -> /home/sandbox/.gemini/settings.json
agents/antigravity/GEMINI.md     -> /home/sandbox/.gemini/GEMINI.md
agents/antigravity/AGENTS.md     -> /home/sandbox/.gemini/AGENTS.md
```

注意点:

- Codex auth は compute node から login node の `$HOME` が見えない構成を避けるため、`--submit` 時に run directory 側へ stage し、`--home` mount で container へ届ける。
- Codex skills は `/home/sandbox/.codex/skills` 全体を bind mount せず、run directory の writable home 内に `common/skills/*` への個別 symlink を作る。これにより Codex が管理する `.codex/skills/.system` を隠さない。
- staged auth を含む run home は job の `trap` で終了時に削除する。
- auth bind は rw。agent CLI が token refresh や session 更新を行う可能性があるため。
- config bind は原則 ro。ただし Codex の `config.toml` は TUI の trust 書き込みが必要なため、Git 管理の正本から run home へコピーした writable file を使う。
- image build logs に token や auth directory は含めない。

## Agent command

現在の command は以下。

Claude:

```bash
# assist: srun --pty で対話 TUI を起動
claude --dangerously-skip-permissions "$(cat /runs/prompt.txt)"

# assist --submit / experiment / campaign / review / multi-review: sbatch 向け非対話実行
claude --print --dangerously-skip-permissions "$(cat /runs/prompt.txt)"
```

Codex:

```bash
# assist: srun --pty で対話 TUI を起動
codex --dangerously-bypass-approvals-and-sandbox --cd /workspace "$(cat /runs/prompt.txt)"

# assist --submit / experiment / campaign / review / multi-review: sbatch 向け非対話実行
codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check --cd /workspace "$(cat /runs/prompt.txt)"
```

Codex CLI 0.139 では `--config <FILE>` ではなく `--config key=value` が override 用であるため、設定ファイルは `/home/sandbox/.codex/config.toml` に配置して読ませる。

Antigravity:

```bash
if command -v agy >/dev/null 2>&1; then
  agy --print "$(cat /runs/prompt.txt)"
elif command -v antigravity >/dev/null 2>&1; then
  antigravity --print "$(cat /runs/prompt.txt)"
else
  gemini "$(cat /runs/prompt.txt)"
fi
```

現在の image では `agy` が確認済み。

## 検証コマンド

静的検証:

```bash
./runtime/agentrun/agentrun validate
```

host 状態確認:

```bash
./runtime/agentrun/agentrun doctor --all
```

ログインノードでは `apptainer` や `uv` が見えない場合がある。その場合は WARN として扱う。今回の検証では、Apptainer は計算ノード上で、uv と agent CLI は image 内で確認済み。

dry-run:

```bash
./runtime/agentrun/agentrun dry-run assist --agent claude --repo . --partition small-creator "..."
```

Slurm smoke:

```bash
./runtime/agentrun/agentrun smoke-test --agent claude --partition small-creator --time 00:05:00 --mem 4000M --submit
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

SIF build test:

```bash
tests/slurm/submit_creator_tests.sh build
```

Agent CLI smoke:

```bash
tests/slurm/submit_creator_tests.sh agents
```

Codex authenticated smoke:

```bash
tests/slurm/submit_creator_tests.sh codex-auth
```

## 運用時の注意

- ログインノードで GPU workload や非標準 Python 実行をしない。
- Python を使う Slurm job を作る場合は、AGENTS.md の uv venv 選択ルールに従う。
- SIF build の cache directory を repository 配下に作らない。
- 既に存在する大量小ファイル cache directory は `rm -rf` で削除しない。
- `.agent-runs/` は実行ログと成果物の置き場であり、Git 管理対象ではない。
- product runtime script に cluster 固有 partition を埋め込まない。
- creator partition は `tests/slurm/` の検証専用。

## 現時点の実用上の見方

このリポジトリは、plan.md の「Slurm + Apptainer + run ledger + agent config source of truth」という骨格については運用可能な状態にある。

特に以下は実証済み。

- SIF image を計算ノードで作成できる。
- container 内で 3 種の agent CLI が起動できる。
- ログインノードから run directory と submit script を作れる。
- Slurm job が live ledger と artifacts を生成し、`verify-run` で検証できる。

一方で、実 agent に長時間作業させ、成果物を元 repo に取り込む運用は、各 workflow ごとに追加検証が必要である。現在の安全側の設計では、agent の作業領域は `.agent-runs/<run_id>/workspace` に閉じているため、元 repo への反映は明示的な確認ステップを挟む。
