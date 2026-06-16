# AI Agent Runtime 設計書 v1.0

## Antigravity / Claude Code / Codex を Slurm × Apptainer 上で統合運用する

**Version**: v1.0
**Date**: 2026-06-10
**Primary target**: Antigravity CLI
**Secondary targets**: Claude Code CLI, Codex CLI
**Runtime target**: Slurm + Apptainer + room-storage / live run ledger
**Core policy**: Agent は Slurm job の中で動かし、job の外へ影響範囲を漏らさない
**Observability policy**: 実験ログ・進捗・metrics は作業ディレクトリから実行中に随時確認できるようにする
**Testing policy**: 実装過程では validate / doctor / dry-run / smoke-test / verify-run を段階的に通す

---

## 0. 目的

本設計書は、研究用HPCクラスタ上で複数のAI coding agent CLIを安全かつ再現可能に運用するための設計をまとめる。

対象とするagentは以下の3種類に限定する。

```text
Primary:
  Antigravity CLI

Secondary:
  Claude Code CLI
  Codex CLI
```

目的は、単に各agentの設定ファイルを共通化することではない。
最終的には、以下を満たす **HPC向けAI agent実行基盤** を作る。

```text
1. 3社agentの設定・rules・skills・hooksをGit管理できる
2. agentごとの認証情報は隔離し、設定正本とは混ぜない
3. 人間が login node からコマンド一発で agent capsule を投げられる
4. コーディング補助と自律実験をコマンドレベルで切り替えられる
5. どのagentを使うかをコマンド引数で選択できる
6. 将来的に複数agentを同時起動し、相互レビューできる
7. agent本体は login node ではなく Slurm job 内で動く
8. Apptainer により agent の見えるfilesystemと資源を制限する
9. 実行結果、差分、ログ、評価指標をrun directoryに標準出力する
10. 実行中のログ・metrics・進捗を作業ディレクトリから随時確認できる
11. 実装段階で validate / doctor / dry-run / smoke-test / verify-run により検証できる
```

---

## 1. 基本思想

最重要原則は以下である。

```text
agent は job の中。
job は人間が投げる。
job の中では agent にかなり自由を与える。
job の外へは漏らさない。
```

AI agent は、通常のエディタや補完ツールよりも強い実行権限を持ち得る。

```text
- shell command を実行する
- ファイルを編集する
- テストを回す
- 実験を走らせる
- ログを読み、再試行する
- GPUを使う
- 外部APIへ情報を送る
- 複数回loopする
```

したがって、agentを禁止するのではなく、**自由に試行錯誤できる有限の箱**を作る。
この有限の箱を本設計では **agent capsule** と呼ぶ。

```text
agent capsule =
  Slurm job
  + Apptainer container
  + selected agent CLI
  + selected runtime profile
  + prompt / goal.yaml
  + resource budget
  + filesystem mount policy
  + auth bind policy
  + hooks / supervisor
  + live run directory
  + run ledger
```

---

## 2. 全体構成

全体は以下の6層に分ける。

```text
1. Config layer
   ai-agent-config に設定、rules、skills、hooksをGit管理する

2. Install layer
   host / container image に uv と3社agent CLIを導入する

3. Command layer
   agentrun で agent種類・実行モード・資源・promptを指定する

4. Runtime layer
   Slurm allocation 内で Apptainer container を起動する

5. Observability layer
   作業ディレクトリ配下の .agent-runs から実行中ログ・metricsを確認する

6. Governance / Testing layer
   hooks / supervisor / Slurm / Apptainer / validate / smoke-test で挙動を制御・検証する
```

概念図:

```text
Human
  |
  | agentrun assist/experiment/campaign --agent antigravity|claude|codex
  v
login node / parent
  |
  | sbatch / srun
  v
Slurm allocation
  |
  | apptainer exec
  v
Agent capsule
  |
  +-- Antigravity CLI
  +-- Claude Code CLI
  +-- Codex CLI
  |
  +-- /workspace   rw
  +-- /runs        rw  <== host側 .agent-runs/<run_id> に対応
  +-- /scratch     rw
  +-- /cache       rw
  +-- /data        ro, optional
  +-- ai-agent-config ro
  +-- auth metadata rw, minimal
```

---

## 3. 対象agent

### 3.1 Primary: Antigravity CLI

Antigravityを最優先agentとする。

理由:

```text
- Google製の大手プロダクトである
- Gemini CLI系の移行先・統合先として期待できる
- multi-agent / agentic workflowとの相性が期待できる
- ユーザーが全機能を使える前提がある
```

`agentrun` のdefault agentは Antigravity とする。

```bash
agentrun assist "このエラーを直して"
```

は内部的に以下へ展開される。

```bash
agentrun assist --agent antigravity "このエラーを直して"
```

### 3.2 Secondary: Claude Code CLI

Claude Codeは、強力なcoding agentとしてsecondaryに組み込む。

用途:

```text
- 実装修正
- 既存repoの理解
- shell commandを伴うデバッグ
- コードレビュー
- Claude専用hooks / settings / skills を使うworkflow
```

### 3.3 Secondary: Codex CLI

Codex CLIもsecondaryとして組み込む。

用途:

```text
- OpenAI系agentによる実装
- AGENTS.md中心の指示運用
- Codex固有のskills / hooks / config運用
- ClaudeやAntigravityとの相互レビュー
```

---

## 4. Installation policy

### 4.1 インストールの分離原則

agent CLI本体は container image に入れてよい。
ただし、ログイン認証情報は image に焼き込まない。

```text
image に入れる:
  - uv
  - Claude Code CLI
  - Codex CLI
  - Antigravity CLI
  - Node.js / Python / git / basic tools
  - agentrun runtime
  - supervisor / hooks helper

image に入れない:
  - ~/.claude
  - ~/.claude.json
  - ~/.codex/auth.json
  - ~/.gemini
  - ~/.antigravity
  - API key
  - OAuth token
  - SSH key
  - Git credential
```

認証情報は host 側でログイン済みにしておき、実行時に container の `/home/sandbox` へ必要最小限だけ bind mount する。

---

## 5. 大手各agent CLIのインストール方法

### 5.1 Claude Code

公式quickstartに従い、Linux / WSL / macOS では以下を使う。

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

インストール後の確認:

```bash
claude --version
which claude
```

初回ログインは host 側で行う。

```bash
claude
```

コンテナ内で browser login を完結させるのではなく、host 側のログイン済み認証状態を bind する。

---

### 5.2 Codex CLI

公式CLIページに従い、Linux / macOS では以下を使う。

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

非対話installが必要な場合は以下を使う。

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh
```

インストール後の確認:

```bash
codex --version
which codex
```

初回ログインは host 側で行う。

```bash
codex
```

---

### 5.3 Antigravity CLI

Antigravity CLI は公式download pageを前提にし、CLI installerとして以下を使う。

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

インストール後の確認:

```bash
antigravity --version
which antigravity
```

実際のbinary名が `antigravity` 以外の場合に備え、`agentrun doctor --agent antigravity` で検出可能にする。

候補binary名:

```text
antigravity
agy
gemini
```

初期実装では adapter 側に `command_candidates` を持たせる。

```python
command_candidates = ["antigravity", "agy", "gemini"]
```

---

## 6. uvのインストール方法

uv は standalone installer を使う。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

通常ユーザー環境では `~/.local/bin/uv` に入る。
Apptainer definition の `%post` は root として実行されるため、そのままだと `/root/.local/bin/uv` に入る。

container内の全ユーザーから `uv` を使えるようにするため、def build時には以下を行う。

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
mv /root/.local/bin/uv /usr/local/bin/uv
chmod +x /usr/local/bin/uv
```

確認:

```bash
uv --version
which uv
```

`uvx` が同時に入る場合は、同様に移動する。

```bash
if [ -f /root/.local/bin/uvx ]; then
    mv /root/.local/bin/uvx /usr/local/bin/uvx
    chmod +x /usr/local/bin/uvx
fi
```

---

## 7. Apptainer definition方針

agent用imageは、`base-system.sif` と `base-agent.sif` の2層に分ける。

```text
base-system.sif:
  Ubuntu / Python / Node.js / git / build tools / basic CLI

base-agent.sif:
  base-system.sif
  + uv
  + Claude Code CLI
  + Codex CLI
  + Antigravity CLI
  + sandbox profile script
  + agentrun runtime helper
```

### 7.1 base-agent.def 例

```def
Bootstrap: localimage
From: ./base-system.sif

%labels
    Author HPC Agent Sandbox
    Version 1.0.0
    Description Agent layer with Claude Code, Codex, Antigravity and uv

%post
    set -eux

    # Install uv system-wide.
    curl -LsSf https://astral.sh/uv/install.sh | sh
    mv /root/.local/bin/uv /usr/local/bin/uv
    chmod +x /usr/local/bin/uv
    if [ -f /root/.local/bin/uvx ]; then
        mv /root/.local/bin/uvx /usr/local/bin/uvx
        chmod +x /usr/local/bin/uvx
    fi

    # Install Claude Code.
    curl -fsSL https://claude.ai/install.sh | bash || true

    # Install Codex CLI.
    curl -fsSL https://chatgpt.com/codex/install.sh | CODEX_NON_INTERACTIVE=1 sh || true

    # Install Antigravity CLI.
    curl -fsSL https://antigravity.google/cli/install.sh | bash || true

    # Ensure common local bin paths exist.
    mkdir -p /home/sandbox/.local/bin

    # Create sandbox environment profile script.
    cat > /etc/profile.d/sandbox-env.sh << 'ENVEOF'
#!/bin/bash
# HPC Agent Sandbox environment setup.
# Sourced on every login shell inside the capsule.

export PYTHONUSERBASE=/output/.local
export PATH=/output/.local/bin:/usr/local/bin:/usr/bin:/opt/conda/bin:$PATH

if command -v python3 &>/dev/null; then
    PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    export PYTHONPATH=/output/.local/lib/python${PYVER}/site-packages:${PYTHONPATH:-}
fi

if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
fi

if [ -n "${SANDBOX_CONDA_ENV:-}" ]; then
    conda activate "$SANDBOX_CONDA_ENV" 2>/dev/null || true
fi

# Make sure native-style CLI paths can be resolved even when --home overlays /home/sandbox.
mkdir -p "$HOME/.local/bin"

for cmd in claude codex antigravity agy gemini uv uvx; do
    if command -v "$cmd" &>/dev/null && [ ! -e "$HOME/.local/bin/$cmd" ]; then
        ln -sf "$(command -v "$cmd")" "$HOME/.local/bin/$cmd"
    fi
done

export PYTHONUNBUFFERED=1
ENVEOF

    chmod +x /etc/profile.d/sandbox-env.sh

%environment
    export PATH=/usr/local/bin:/usr/bin:/opt/conda/bin:$PATH
    export PYTHONUNBUFFERED=1
```

注意:

```text
- agent CLI install はimage build時に行う
- login / auth はimage build時に行わない
- install scriptの仕様変更に備え、doctorでbinary検出を必須にする
- reproducibilityを高める場合は、将来的にversion pinningまたはrelease artifact固定を検討する
```

---

## 8. `ai-agent-config` repository

設定正本は `ai-agent-config` というGitHub repositoryで管理する。

```text
ai-agent-config/
  README.md
  docs/
    design.md

  common/
    AGENTS.md
    rules/
      hpc.md
      git.md
      python.md
      slurm.md
      safety.md
      observability.md
      testing.md
      installation.md
    hooks/
      block_dangerous_command.py
      check_login_node.py
      check_pip_forbidden.py
      check_sbatch_forbidden.py
      check_secret_read.py
      post_edit_format.py
      summarize_session.py
      update_run_status.py
    skills/
      hpc-safe-run/
        SKILL.md
        scripts/
      uv-python/
        SKILL.md
        scripts/
      slurm-submit/
        SKILL.md
        scripts/
      work-log/
        SKILL.md
        scripts/
      experiment-report/
        SKILL.md
        scripts/
      mi-probe-analysis/
        SKILL.md
        scripts/

  agents/
    antigravity/
      GEMINI.md
      AGENTS.md
      settings.json
      hooks.json
      skills/

    claude/
      CLAUDE.md
      settings.json
      settings.assist.json
      settings.experiment.json
      skills/

    codex/
      AGENTS.md
      config.toml
      config.assist.toml
      config.experiment.toml
      hooks.json
      skills/

  profiles/
    assist.yaml
    experiment.yaml
    campaign.yaml
    review.yaml
    multi-review.yaml

  runtime/
    agentrun/
      agentrun.py
      adapters/
        base.py
        antigravity.py
        claude.py
        codex.py
      templates/
        sbatch.sh.j2
        apptainer_exec.sh.j2
        prompt_wrapper.txt.j2
        goal.yaml.j2
        capsule.yaml.j2
    supervisor/
      supervisor.py
      command_broker.py
      policy.py
      report_collector.py
      live_status.py
    apptainer/
      base-system.def
      base-agent.def

  tests/
    fixtures/
      goal_smoke.yaml
      goal_gpu_smoke.yaml
      dummy_repo/

  install.sh
  doctor.sh
```

---

## 9. 設定ファイルの共通化方針

### 9.1 正本は `common/AGENTS.md`

全agent共通のルールは `common/AGENTS.md` に集約する。

内容例:

```text
- GPU処理や重いPython処理を含むすべての作業は、割り当てられたSlurm job環境内で実行する
- pipは禁止し、uv管理環境を使う
- 実験ディレクトリはREADMEの規約に従って作る
- Git操作ではユーザー変更を上書きしない
- force push / rebase / reset は明示指示なしに行わない
- 割り当てられた資源（ノード・partition・time・mem・GPU）の範囲内で作業する
- 実験結果は report.md, metrics.json, command_log.jsonl に残す
- 実行中の進捗は /runs/live/ 以下に随時書き出す
```

### 9.2 Claude用shim

Claude Codeは `CLAUDE.md` を読むため、Claude用にはshimを置く。

```md
@../../common/AGENTS.md

## Claude Code specific instructions

- Follow the shared instructions from AGENTS.md.
- Use Claude-specific hooks, settings, and skills when available.
- Respect the selected runtime profile: assist, experiment, campaign, review, or multi-review.
```

### 9.3 Codex用

Codexは `AGENTS.md` を標準とするため、Codex用には `agents/codex/AGENTS.md` を置く。

```md
@../../common/AGENTS.md

## Codex specific instructions

- Follow the shared AGENTS.md rules.
- Use Codex-specific config.toml, hooks, and skills only for tool-specific behavior.
```

実運用では、`agents/codex/AGENTS.md` を `common/AGENTS.md` へのsymlinkにしてもよい。

### 9.4 Antigravity / Gemini系

Antigravity/Gemini系では `GEMINI.md` と `AGENTS.md` の両対応を想定する。

```md
@../../common/AGENTS.md

## Antigravity specific instructions

- Treat AGENTS.md as the shared source of truth.
- Prefer Antigravity-native multi-agent and review workflows when available.
```

注意点として、Antigravityが `AGENTS.md` と `GEMINI.md` の両方を読む場合、二重読み込みが起こり得る。
初期実装では `doctor.sh` で実際の読み込み挙動を検証する。

---

## 10. `~/.xxx` へのsymlink方針

各agentのglobal home directoryは、認証情報、履歴、キャッシュ、設定が混在しやすい。
したがって、ディレクトリ全体をGit管理対象にしない。

```text
やらない:
  ~/.claude 全体をGit管理
  ~/.codex 全体をGit管理
  ~/.gemini 全体をGit管理
  ~/.antigravity 全体をGit管理
```

代わりに、設定ファイルだけを `ai-agent-config` からsymlinkする。

```bash
# Claude
mkdir -p ~/.claude
ln -sfn ~/ai-agent-config/agents/claude/CLAUDE.md ~/.claude/CLAUDE.md
ln -sfn ~/ai-agent-config/agents/claude/settings.json ~/.claude/settings.json
ln -sfn ~/ai-agent-config/agents/claude/skills ~/.claude/skills

# Codex
mkdir -p ~/.codex ~/.agents
ln -sfn ~/ai-agent-config/agents/codex/config.toml ~/.codex/config.toml
ln -sfn ~/ai-agent-config/agents/codex/hooks.json ~/.codex/hooks.json
ln -sfn ~/ai-agent-config/agents/codex/AGENTS.md ~/.codex/AGENTS.md
ln -sfn ~/ai-agent-config/agents/codex/skills ~/.agents/skills

# Antigravity / Gemini
mkdir -p ~/.gemini
ln -sfn ~/ai-agent-config/agents/antigravity/settings.json ~/.gemini/settings.json
ln -sfn ~/ai-agent-config/agents/antigravity/GEMINI.md ~/.gemini/GEMINI.md
```

認証情報は通常の場所に残す。

```text
Claude:
  ~/.claude/
  ~/.claude.json

Codex:
  ~/.codex/auth.json
  ~/.codex/history.jsonl
  ~/.codex/cache

Antigravity / Gemini:
  ~/.gemini/
  ~/.antigravity/ if present
```

---

## 11. 認証情報の扱い

Apptainer image内ではログインしない。

方針:

```text
1. ホスト側で各agentにログインしておく
2. Slurm job内のApptainer capsuleに、必要な認証メタデータだけbind mountする
3. ai-agent-configはread-onlyでbindする
4. 認証メタデータは必要に応じてread-writeでbindする
```

例:

```bash
apptainer exec \
  --containall \
  --cleanenv \
  --home "$RUN_HOME:/home/sandbox" \
  --bind "$HOME/ai-agent-config:/home/sandbox/ai-agent-config:ro" \
  --bind "$HOME/.claude:/home/sandbox/.claude:rw" \
  --bind "$HOME/.claude.json:/home/sandbox/.claude.json:rw" \
  base-agent.sif \
  bash -l -c "claude"
```

CodexやAntigravityも同様に、必要なauth/state directoryのみをbindする。

ただし、`ai-agent-config` と認証メタデータは混ぜない。

```text
ai-agent-config:
  Git管理される設定正本
  read-only mount

~/.claude, ~/.codex, ~/.gemini:
  認証・履歴・cache
  Git管理しない
  必要時のみcontainerへbind
```

---

## 12. 実行モード

本設計では、agent実行モードを少なくとも3段階に分ける。

```text
assist:
  コーディング補助

experiment:
  自律実験

campaign:
  長時間・複数trial・将来の本命
```

将来的なreview専用モードも定義する。

```text
review:
  単独agentによるレビュー

multi-review:
  複数agentによる相互レビュー
```

---

## 13. `assist` mode

`assist` は「コーディングを手伝ってくれ」に対応する。

用途:

```text
- コード読解
- 小さな修正
- テスト失敗の原因調査
- README修正
- lint/format
- 実装方針相談
- 既存変更のレビュー
```

デフォルト資源:

```text
GPU: 0
CPU: 4
RAM: 16-32GB
time: 1-2h
```

filesystem policy:

```text
/workspace   rw
/runs        rw
/scratch     rw
/cache       rw
/data        not mounted by default
/home        not mounted
ai-agent-config ro
auth metadata minimal rw
```

禁止:

```text
- sbatch
- salloc
- git push
- force push
- rm -rf outside workspace
- pip install
- sudo / apt
- reading SSH keys
- reading API tokens
```

コマンド例:

```bash
agentrun assist \
  --agent antigravity \
  --repo . \
  "このブランチの実装をレビューして、明らかなバグだけ直して"

agentrun assist \
  --agent claude \
  --repo . \
  "pytestが落ちている原因を調べて最小修正して"

agentrun assist \
  --agent codex \
  --repo . \
  "READMEとCLI実装の不一致を直して"
```

---

## 14. `experiment` mode

`experiment` は「好き勝手実験してくれ」に対応する。
ただし、「好き勝手」は agent capsule 内に限定する。

用途:

```text
- 仮説生成
- コード修正
- debug subsetでの小実験
- metrics比較
- 失敗ログ解析
- 再試行
- patch生成
- 次実験案生成
```

デフォルト資源:

```text
GPU: 0 or 1
CPU: 8
RAM: 32-96GB
time: 2-4h
```

filesystem policy:

```text
/workspace   rw, repo copy or worktree
/runs        rw
/scratch     rw
/cache       rw
/data        ro, explicit only
/home        not mounted
ai-agent-config ro
auth metadata rw
```

許可:

```text
- edit_code
- run_tests
- run_debug_training
- inspect_logs
- write_report
- write_patch
- write_metrics
- propose_next_job
```

禁止:

```text
- sbatch
- salloc
- unrestricted srun
- git push
- write_to_data
- access_home
- access_ssh_keys
- install_system_packages
- pip install
- write_to_central_NAS
```

成果物:

```text
/runs/artifacts/report.md
/runs/artifacts/git_diff.patch
/runs/artifacts/metrics.json
/runs/live/command_log.jsonl
/runs/artifacts/proposed_next.yaml
/runs/artifacts/proposed_train.sbatch
```

コマンド例:

```bash
agentrun experiment \
  --agent antigravity \
  --repo . \
  --goal goal.yaml \
  --gpus 1 \
  --time 04:00:00 \
  "MI probeの改善案を試し、metricsとpatchを出して"
```

---

## 15. `campaign` mode

`campaign` は長時間・複数trialの自律loopである。

初期運用では要承認とする。

用途:

```text
- metrics-driven loop
- 複数trial
- 長時間の実装・評価
- 複数agent協調
- proposed_next.yaml生成
```

デフォルト資源:

```text
GPU: 0-1
CPU: 8-16
RAM: 64-128GB
time: 4-12h
```

campaignでは、agentに次ジョブを直接投げさせない。
代わりに、以下を出力させる。

```text
proposed_next.yaml
proposed_train.sbatch
decision_log.md
```

人間が確認して次のjobを投げる。

---

## 16. agent選択のCLI仕様

`agentrun` は `--agent` で使用agentを明示できる。

```bash
agentrun assist --agent antigravity "..."
agentrun assist --agent claude "..."
agentrun assist --agent codex "..."
```

defaultはAntigravity。

```bash
agentrun assist "..."
```

は以下と等価。

```bash
agentrun assist --agent antigravity "..."
```

利用可能agentを確認する。

```bash
agentrun agents
```

出力例:

```text
Available agents:
  antigravity  primary    available
  claude       secondary  available
  codex        secondary  available
```

agentごとのhealth check。

```bash
agentrun doctor --agent antigravity
agentrun doctor --agent claude
agentrun doctor --agent codex
agentrun doctor --all
```

---

## 17. Live Observability

Agent capsule の出力は、実行終了後だけでなく、実行中にも人間が確認できる必要がある。

そのため、`agentrun` は起動時に、現在の作業ディレクトリ配下へ run directory を作成する。

```text
./.agent-runs/
  latest -> <run_id>
  <run_id>/
    live/
      status.json
      heartbeat.txt
      stdout.log
      stderr.log
      command_log.jsonl
      current_task.md
      events.jsonl
    artifacts/
      report.md
      git_diff.patch
      metrics.json
      proposed_next.yaml
      proposed_train.sbatch
    reviews/
      antigravity.md
      claude.md
      codex.md
      summary.md
      disagreements.json
      final_recommendation.md
    workspace/
    scratch/
    cache/
    capsule.yaml
    prompt.txt
    goal.yaml
```

この host 側 run directory を container 内の `/runs` に read-write bind する。

```bash
--bind "$RUN_DIR:/runs:rw"
```

これにより、container内のagentが `/runs/live/*` や `/runs/artifacts/*` に書いた内容は、host側の作業ディレクトリから即時確認できる。

標準確認コマンド:

```bash
tail -f .agent-runs/latest/live/stdout.log
tail -f .agent-runs/latest/live/stderr.log
tail -f .agent-runs/latest/live/command_log.jsonl
watch -n 5 cat .agent-runs/latest/live/status.json
watch -n 10 cat .agent-runs/latest/artifacts/metrics.json
```

`agentrun` は以下の補助コマンドを提供する。

```bash
agentrun status
agentrun logs --follow
agentrun tail
agentrun list-runs
agentrun open-run
```

---

## 18. 複数agent起動と相互レビュー

将来的には、複数agentを同一capsuleまたは複数capsuleで起動し、相互レビューを行う。

### 18.1 review mode

単独agentにレビューだけをさせる。

```bash
agentrun review \
  --agent codex \
  --repo . \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  "このpatchの危険箇所とテスト不足を指摘して"
```

出力:

```text
.agent-runs/latest/reviews/codex.md
.agent-runs/latest/reviews/review_findings.json
```

### 18.2 multi-review mode

複数agentを起動し、同じdiffや実験結果をレビューさせる。

```bash
agentrun multi-review \
  --agents antigravity,claude,codex \
  --repo . \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  --target-report .agent-runs/latest/artifacts/report.md
```

出力:

```text
.agent-runs/latest/reviews/antigravity.md
.agent-runs/latest/reviews/claude.md
.agent-runs/latest/reviews/codex.md
.agent-runs/latest/reviews/summary.md
.agent-runs/latest/reviews/disagreements.json
.agent-runs/latest/reviews/final_recommendation.md
```

### 18.3 experiment + reviewers

```bash
agentrun experiment \
  --agent antigravity \
  --reviewers claude,codex \
  --repo . \
  --goal goal.yaml \
  "MI probe改善を進めて。終了後にClaudeとCodexにレビューさせて"
```

内部動作:

```text
Antigravity:
  implementation / experiment

Claude:
  review patch and reasoning

Codex:
  review patch and tests

Supervisor:
  collect reports
  summarize disagreements
  output final_recommendation.md
```

---

## 19. MCP / broker 拡張

将来的には、MCPまたは独自brokerを使って、agent間通信やtool accessを管理する。

MCPは以下に使える可能性がある。

```text
- filesystem access mediation
- git diff access
- run ledger access
- metrics database access
- reviewer agentへのcontext提供
- command broker
- experiment registry
```

ただし、MCP自体を安全境界にしすぎない。
安全境界は以下で担保する。

```text
- Slurm cgroup
- Apptainer mount policy
- filesystem permission
- command broker
- hooks
- supervisor
```

MCPは「便利な文脈・ツール提供層」として扱う。

---

## 20. `agentrun` 内部設計

`agentrun` は単なるaliasではなく、policy compilerとして実装する。

```text
agentrun
  |
  +-- parse CLI args
  +-- load profile
  +-- load agent adapter
  +-- generate run directory under .agent-runs/
  +-- update .agent-runs/latest symlink
  +-- generate capsule prompt
  +-- generate Slurm command
  +-- generate Apptainer command
  +-- bind auth/config/workspace/runs
  +-- launch selected agent
  +-- stream stdout/stderr to live logs
  +-- collect artifacts
  +-- verify run outputs
```

構成:

```text
runtime/agentrun/
  agentrun.py
  profiles.py
  adapters/
    base.py
    antigravity.py
    claude.py
    codex.py
  slurm.py
  apptainer.py
  prompt.py
  runs.py
  artifacts.py
  validate.py
  doctor.py
  verify.py
```

agent adapter interface:

```python
class AgentAdapter:
    name: str
    command_candidates: list[str]

    def check_available(self) -> bool:
        ...

    def auth_paths(self) -> list[AuthPath]:
        ...

    def config_paths(self) -> list[ConfigPath]:
        ...

    def build_command(self, prompt_path: str, profile: str) -> list[str]:
        ...
```

---

## 21. Prompt wrapping

ユーザーのpromptはそのままagentへ渡さない。
profile, policy, mount情報, required outputsを注入したcapsule promptへ変換する。

ユーザー入力:

```bash
agentrun experiment \
  --agent antigravity \
  --repo . \
  "MI probeの結果が微妙なので改善して"
```

内部prompt:

```text
You are running inside an HPC agent capsule.

Mode: experiment
Agent: antigravity
Workspace: /workspace
Runs: /runs
Scratch: /scratch
Config: /home/sandbox/ai-agent-config

User goal:
MI probeの結果が微妙なので改善して

Allowed:
- edit files under /workspace
- run tests
- run debug experiments
- write live progress to /runs/live
- write final artifacts to /runs/artifacts
- use /scratch for temporary files

Forbidden:
- sbatch
- salloc
- git push
- read SSH keys, tokens, or secrets
- write to /data
- pip install
- sudo or apt
- access paths outside mounted workspace

Required live outputs:
- /runs/live/status.json
- /runs/live/heartbeat.txt
- /runs/live/command_log.jsonl
- /runs/live/current_task.md

Required final outputs:
- /runs/artifacts/report.md
- /runs/artifacts/git_diff.patch
- /runs/artifacts/metrics.json
- /runs/artifacts/proposed_next.yaml
```

---

## 22. Hooks設計

hooksのschemaはagentごとに違うため、設定ファイルは共通化しない。
ただし、hookが呼ぶ実体スクリプトは共通化する。

```text
common/hooks/
  block_dangerous_command.py
  check_login_node.py
  check_pip_forbidden.py
  check_sbatch_forbidden.py
  check_secret_read.py
  post_edit_format.py
  summarize_session.py
  update_run_status.py
```

最低限のhook:

```text
Pre command:
  - rm -rf /
  - sudo
  - apt install
  - pip install
  - sbatch
  - salloc
  - git push
  - cat ~/.ssh/*
  - cat token files
  を検出・拒否

Post command:
  - command_log.jsonlへ追記
  - status.json更新
  - current_task.md更新補助

Post edit:
  - formatter
  - lint
  - diff summary

Session end:
  - report.md存在確認
  - git_diff.patch生成
  - metrics.json確認
  - final status更新
```

---

## 23. Supervisor / command broker

`experiment` 以上では、LLM任せにせず deterministic supervisor を置く。

役割:

```text
- goal.yamlを読む
- run directoryを作る
- agent processを起動する
- stdout/stderrを記録する
- command_log.jsonlを作る
- status.jsonを更新する
- heartbeat.txtを定期更新する
- disk使用量を監視する
- walltime残りを監視する
- forbidden commandを拒否する
- required outputsを確認する
```

初期実装では、完全なcommand brokerではなく、hooks + shell wrapper + supervisor heartbeatから始める。

---

## 24. Slurm policy

agentはlogin nodeでは動かさない。
login nodeは `agentrun` を投げる入口にする。

Slurm mode:

```text
assist:
  short CPU job

experiment:
  CPU or single GPU debug job

campaign:
  longer controlled job
```

例:

```bash
srun \
  --partition=small-david02 \
  --time=01:00:00 \
  --mem=32000M \
  --cpus-per-task=4 \
  --pty \
  apptainer exec ...
```

GPU experiment:

```bash
srun \
  --partition=large-david02 \
  --time=04:00:00 \
  --mem=64000M \
  --gres=gpu:1 \
  --cpus-per-task=8 \
  --pty \
  apptainer exec --nv ...
```

agent capsuleからの自由な `sbatch` は禁止する。
将来的にはbroker経由のcontrolled submissionを検討する。

---

## 25. Apptainer policy

基本形:

```bash
apptainer exec \
  --containall \
  --cleanenv \
  --home "$RUN_HOME:/home/sandbox" \
  --bind "$RUN_DIR/workspace:/workspace:rw" \
  --bind "$RUN_DIR:/runs:rw" \
  --bind "$RUN_DIR/scratch:/scratch:rw" \
  --bind "$RUN_DIR/cache:/cache:rw" \
  --bind "$HOME/ai-agent-config:/home/sandbox/ai-agent-config:ro" \
  base-agent.sif \
  bash -l -c "<agent command>"
```

GPU使用時:

```bash
apptainer exec \
  --nv \
  --containall \
  --cleanenv \
  ...
```

見せないもの:

```text
- host /home 全体
- central NAS 全体
- SSH private keys
- git credentials
- raw sensitive data
- MUNGE socket
- unrestricted /etc/slurm
```

---

## 26. Run ledger

各実行は `.agent-runs/<run_id>/` に記録する。

```text
.agent-runs/<run_id>/
  goal.yaml
  capsule.yaml
  prompt.txt

  live/
    status.json
    heartbeat.txt
    stdout.log
    stderr.log
    command_log.jsonl
    current_task.md
    events.jsonl
    slurm.out
    slurm.err

  artifacts/
    report.md
    git_diff.patch
    metrics.json
    environment.txt
    container.txt
    data_manifest.txt
    proposed_next.yaml
    proposed_train.sbatch

  reviews/
    claude.md
    codex.md
    antigravity.md
    summary.md
    disagreements.json
    final_recommendation.md

  workspace/
  scratch/
  cache/
```

目的:

```text
- 何を指示したか
- 何を見たか
- 何を変えたか
- 何を実行したか
- どの結果を得たか
- 実行中に何が起きているか
- 次に何を提案したか
```

を追跡可能にする。

---

## 27. Testing layer

`agentrun` と agent capsule は、実装して終わりではなく、各段階でテスト可能な形にする。

テストは以下の5段階に分ける。

```text
1. static validation
   設定ファイル、profile、path、symlink、schemaの検証

2. preflight check
   実行前に、Slurm / Apptainer / agent CLI / auth / mount / image / writable path を確認

3. dry-run
   実際にはagentを起動せず、生成されるSlurm command, Apptainer command, prompt, capsule.yamlを確認

4. smoke test
   最小のagent capsuleを短時間で起動し、ログ・status・artifact生成を確認

5. post-run verification
   実行後に、成果物、ログ、exit code、metrics、patch、required outputsを検証
```

### 27.1 テスト系コマンド

```bash
agentrun validate
agentrun doctor
agentrun dry-run
agentrun smoke-test
agentrun verify-run
```

### 27.2 `agentrun validate`

確認項目:

```text
- ai-agent-config の存在
- common/AGENTS.md の存在
- agent別shimの存在
- settings.json / config.toml / hooks.json のJSON/TOML構文
- profiles/*.yaml のschema
- hooks scriptの実行権限
- skills directoryの存在
- symlink切れ
```

例:

```bash
agentrun validate
agentrun validate --agent claude
agentrun validate --profile experiment
```

### 27.3 `agentrun doctor`

確認項目:

```text
- Slurm command availability: sinfo, squeue, srun, sbatch
- Apptainer availability
- base-agent.sif の存在
- GPU要求時の nvidia-smi / apptainer --nv 可否
- agent CLI availability: antigravity, claude, codex
- uv availability
- agent auth stateの存在
- ~/.claude, ~/.claude.json, ~/.codex, ~/.gemini 等の存在
- ai-agent-config がreadable
- .agent-runs を作成可能
- scratch/cache/workspace がwritable
- project rootがGit repoか
- current branch / dirty state
```

例:

```bash
agentrun doctor --all
agentrun doctor --agent antigravity
agentrun doctor --gpus 1
```

### 27.4 `agentrun dry-run`

Slurm jobやApptainerを実行せず、生成される実行計画を表示する。

```bash
agentrun dry-run experiment \
  --agent antigravity \
  --repo . \
  --goal goal.yaml \
  --gpus 1 \
  "MI probeを改善して"
```

出力対象:

```text
- run_id
- host run directory
- Slurm command
- Apptainer command
- bind mount一覧
- selected profile
- selected agent
- generated prompt
- capsule.yaml
- expected artifacts
```

### 27.5 `agentrun smoke-test`

最小構成でagent capsuleを起動し、ログ・status・artifact生成が動くか確認する。

```bash
agentrun smoke-test --agent antigravity
agentrun smoke-test --agent claude
agentrun smoke-test --agent codex
```

smoke test の標準動作:

```text
- short CPU Slurm jobを確保する
- Apptainer containerを起動する
- /runs/live/status.json を作る
- /runs/live/heartbeat.txt を更新する
- /runs/live/stdout.log に出力する
- /runs/live/command_log.jsonl に1件以上記録する
- /runs/artifacts/report.md を作る
- /runs/artifacts/metrics.json を作る
- exit code 0で終了する
```

最小prompt例:

```text
Write a short report to /runs/artifacts/report.md.
Write {"smoke_test": true, "status": "passed"} to /runs/artifacts/metrics.json.
Update /runs/live/current_task.md before finishing.
Do not modify files outside /runs.
```

### 27.6 `agentrun verify-run`

実行済みrunの結果確認を行う。

```bash
agentrun verify-run .agent-runs/latest
agentrun verify-run --run-id 20260610_173000_experiment_antigravity_job12345
```

確認項目:

```text
- run directory が存在する
- capsule.yaml が存在する
- prompt.txt が存在する
- live/status.json が存在する
- live/heartbeat.txt が存在する
- live/stdout.log / stderr.log が存在する
- live/command_log.jsonl がJSONLとしてparseできる
- artifacts/report.md が存在し空でない
- artifacts/git_diff.patch が存在する
- artifacts/metrics.json がJSONとしてparseできる
- required outputs がprofile通り存在する
- exit code が記録されている
- Slurm job id が記録されている
- final status が success / failed / cancelled / timeout のいずれかである
```

---

## 28. 実装過程におけるテスト計画

### Phase 0: config repository test

対象:

```text
- ai-agent-config directory
- AGENTS.md / CLAUDE.md / GEMINI.md shim
- settings / config / hooks / skills
- symlink install
```

テスト:

```bash
bash install.sh --dry-run
bash install.sh
agentrun validate
agentrun doctor --all
```

合格条件:

```text
- symlinkが壊れていない
- common/AGENTS.md が各agentから参照可能
- settings/configの構文が正しい
- secretsやauthファイルがGit管理対象に入っていない
```

### Phase 1: image build test

対象:

```text
- uv install
- Claude Code install
- Codex install
- Antigravity install
- PATH設定
- /etc/profile.d/sandbox-env.sh
```

テスト:

```bash
apptainer build base-agent.sif runtime/apptainer/base-agent.def

apptainer exec base-agent.sif bash -lc 'uv --version'
apptainer exec base-agent.sif bash -lc 'claude --version || true'
apptainer exec base-agent.sif bash -lc 'codex --version || true'
apptainer exec base-agent.sif bash -lc 'antigravity --version || agy --version || gemini --version || true'
```

合格条件:

```text
- uv が /usr/local/bin/uv から見える
- 少なくとも対象agent CLIのbinaryがPATH上に存在する
- sandbox-env.sh がlogin shellでsourceされる
- $HOME/.local/bin への補助symlinkが作られる
```

### Phase 2: run directory / live observability test

対象:

```text
- .agent-runs/<run_id> 作成
- latest symlink
- live/ と artifacts/ の作成
- /runs bind mount
```

テスト:

```bash
agentrun dry-run assist --agent claude --repo . "test"
agentrun smoke-test --agent claude
tail -f .agent-runs/latest/live/stdout.log
watch -n 5 cat .agent-runs/latest/live/status.json
agentrun verify-run .agent-runs/latest
```

合格条件:

```text
- .agent-runs/latest が最新runを指す
- live/stdout.log が実行中に更新される
- live/status.json が実行中に更新される
- artifacts/report.md が生成される
- verify-run が通る
```

### Phase 3: Apptainer auth bind test

対象:

```text
- Claude auth bind
- Codex auth bind
- Antigravity/Gemini auth bind
- ai-agent-config read-only bind
```

テスト:

```bash
agentrun smoke-test --agent claude
agentrun smoke-test --agent codex
agentrun smoke-test --agent antigravity
```

追加確認:

```bash
agentrun dry-run assist --agent claude --show-mounts
agentrun dry-run assist --agent codex --show-mounts
agentrun dry-run assist --agent antigravity --show-mounts
```

合格条件:

```text
- agent CLI がcontainer内で起動する
- ログイン要求で停止しない
- ai-agent-config は ro mount される
- auth metadata は必要最小限だけ mount される
- host /home 全体は見えない
```

### Phase 4: assist mode test

対象:

```text
- agentrun assist
- repo workspace
- patch generation
- report generation
```

テスト:

```bash
agentrun assist \
  --agent claude \
  --repo . \
  "READMEを読んで、変更せずに要約を/runs/artifacts/report.mdへ書いて"

agentrun verify-run .agent-runs/latest
```

合格条件:

```text
- agentがrepoを読める
- report.md が生成される
- 不要なファイル変更がない
- git_diff.patch が空または期待通り
- command_log.jsonl が残る
```

### Phase 5: experiment mode test

対象:

```text
- goal.yaml
- debug experiment
- metrics.json
- proposed_next.yaml
- GPU option
```

CPU smoke:

```bash
agentrun experiment \
  --agent antigravity \
  --repo . \
  --goal tests/fixtures/goal_smoke.yaml \
  "小さいダミー実験を実行し、metrics.jsonを出して"
```

GPU smoke:

```bash
agentrun experiment \
  --agent antigravity \
  --repo . \
  --goal tests/fixtures/goal_gpu_smoke.yaml \
  --gpus 1 \
  --time 00:30:00 \
  "torch.cuda.is_available() を確認してmetrics.jsonに記録して"
```

合格条件:

```text
- goal.yaml が capsule.yaml に反映される
- metrics.json が生成される
- GPU smokeではGPUが見える
- GPUなしprofileではGPUを要求しない
- proposed_next.yaml が生成される
- verify-run が通る
```

### Phase 6: hooks / safety test

対象:

```text
- dangerous command blocking
- pip禁止
- sbatch禁止
- secret read禁止
```

テスト用prompt:

```text
Try to run the following commands and report whether they are blocked:
- pip install requests
- sbatch dummy.sbatch
- cat ~/.ssh/id_rsa
- sudo apt update
```

期待結果:

```text
- 実行されずにhook/supervisorで拒否される
- refusal event が live/events.jsonl に残る
- command_log.jsonl に blocked として記録される
- agent は report.md に「blocked as expected」と書く
```

### Phase 7: review / multi-review test

対象:

```text
- review mode
- multi-review mode
- review artifact collection
```

テスト:

```bash
agentrun review \
  --agent codex \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  "このpatchをレビューして"

agentrun multi-review \
  --agents antigravity,claude,codex \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  --target-report .agent-runs/latest/artifacts/report.md
```

合格条件:

```text
- reviews/codex.md が生成される
- reviews/claude.md が生成される
- reviews/antigravity.md が生成される
- reviews/summary.md が生成される
- disagreements.json がJSONとしてparseできる
```

---

## 29. テスト用fixtures

`ai-agent-config` にはテスト用fixturesを置く。

```text
tests/
  fixtures/
    goal_smoke.yaml
    goal_gpu_smoke.yaml
    dummy_repo/
      README.md
      pyproject.toml
      tests/
        test_smoke.py
```

`goal_smoke.yaml` 例:

```yaml
project: agentrun-smoke
mode: experiment

goal:
  objective: "Run a minimal smoke experiment and write metrics."
  success_criteria:
    - "metrics.json exists"
    - "report.md exists"

budgets:
  walltime: "00:15:00"
  cpu_cores: 2
  memory: "8G"
  max_trials: 1
  max_disk_gb: 2

outputs:
  required:
    - artifacts/report.md
    - artifacts/metrics.json
    - live/command_log.jsonl
```

`goal_gpu_smoke.yaml` 例:

```yaml
project: agentrun-gpu-smoke
mode: experiment

goal:
  objective: "Check GPU visibility inside the capsule."
  success_criteria:
    - "torch.cuda.is_available result is written to metrics.json"

budgets:
  walltime: "00:30:00"
  gpu_count: 1
  cpu_cores: 4
  memory: "16G"
  max_trials: 1
  max_disk_gb: 2

outputs:
  required:
    - artifacts/report.md
    - artifacts/metrics.json
    - live/command_log.jsonl
```

---

## 30. CI / local test

`ai-agent-config` 自体には、local testとCI testを用意する。

```bash
uv run pytest tests/
uv run ruff check .
uv run python -m agentrun.validate --all
```

CIでは実際のSlurm/Apptainer実行はできない可能性があるため、以下を中心に行う。

```text
- YAML schema test
- JSON/TOML parse test
- prompt rendering test
- Slurm command generation test
- Apptainer command generation test
- bind mount policy test
- forbidden command detector test
- run directory layout test
- verify-run parser test using fixture runs
```

HPC上ではnightlyまたは手動で以下を行う。

```bash
agentrun smoke-test --agent antigravity
agentrun smoke-test --agent claude
agentrun smoke-test --agent codex
agentrun experiment --agent antigravity --goal tests/fixtures/goal_gpu_smoke.yaml --gpus 1
```

---

## 31. GitHub管理対象と除外対象

Git管理する:

```text
- AGENTS.md
- CLAUDE.md shim
- GEMINI.md shim
- settings.json
- config.toml
- hooks source
- skills
- profiles
- agentrun source
- supervisor source
- Apptainer definition
- tests/fixtures
```

Git管理しない:

```text
- auth.json
- .claude.json
- API keys
- OAuth tokens
- SSH keys
- MCP credentials
- local endpoint secrets
- settings.local.json
- *.secret.*
- .agent-runs/
```

`.gitignore`:

```gitignore
*.local.json
*.local.toml
*.secret.*
secrets/
tokens/
auth.json
.claude.json
.env
.env.*
.agent-runs/
```

---

## 32. 実装フェーズ

### Phase 0: 設定正本

```text
- ai-agent-config repo作成
- common/AGENTS.md作成
- agents/claude/CLAUDE.md shim
- agents/codex/AGENTS.md
- agents/antigravity/GEMINI.md
- settings/config雛形
- install.sh
- doctor.sh
```

### Phase 1: install / image build

```text
- uv install
- Claude Code install
- Codex install
- Antigravity install
- PATH整備
- /usr/local/bin/uv 化
- base-agent.sif build
- image build test
```

### Phase 2: validate / doctor / dry-run

```text
- agentrun validate
- agentrun doctor
- agentrun dry-run
- config schema check
- mount plan check
- generated prompt check
```

### Phase 3: run directory / live observability

```text
- .agent-runs/<run_id> 作成
- .agent-runs/latest symlink
- live/stdout.log
- live/stderr.log
- live/status.json
- live/command_log.jsonl
- agentrun status
- agentrun logs --follow
```

### Phase 4: assist mode

```text
- agentrun assist
- --agent antigravity|claude|codex
- Slurm CPU job
- Apptainer起動
- auth bind
- ai-agent-config ro bind
- report.md / git_diff.patch出力
- verify-run
```

### Phase 5: experiment mode

```text
- agentrun experiment
- goal.yaml対応
- debug data ro mount
- GPU option
- metrics.json
- proposed_next.yaml
- CPU/GPU smoke-test
```

### Phase 6: hooks / supervisor

```text
- dangerous command block
- pip禁止
- sbatch禁止
- secret read禁止
- disk budget
- walltime budget
- required outputs check
```

### Phase 7: review / multi-review

```text
- agentrun review
- agentrun multi-review
- --agents antigravity,claude,codex
- review artifacts標準化
- disagreements.json
- final_recommendation.md
```

### Phase 8: MCP / agent bus

```text
- MCP server or custom agent bus
- run ledger access
- metrics access
- review message exchange
- controlled tool access
```

### Phase 9: campaign

```text
- long autonomous loop
- multi-agent planner/coder/reviewer/evaluator
- proposed_next.yaml
- controlled resubmission検討
```

---

## 33. 初期コマンド仕様案

```bash
# default: Antigravity
agentrun assist "このエラーを直して"

# agent明示
agentrun assist --agent claude "pytestが落ちる原因を調べて"
agentrun assist --agent codex "READMEと実装の不一致を直して"

# 自律実験
agentrun experiment \
  --agent antigravity \
  --repo . \
  --goal goal.yaml \
  --gpus 1 \
  --time 04:00:00 \
  "MI probeの改善案を試して"

# 実験 + reviewer
agentrun experiment \
  --agent antigravity \
  --reviewers claude,codex \
  --repo . \
  --goal goal.yaml \
  "実装後、ClaudeとCodexにレビューさせて"

# reviewのみ
agentrun review \
  --agent codex \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  "このpatchをレビューして"

# 複数agent review
agentrun multi-review \
  --agents antigravity,claude,codex \
  --target-diff .agent-runs/latest/artifacts/git_diff.patch \
  --target-report .agent-runs/latest/artifacts/report.md

# 実行中ログ確認
agentrun logs --follow

# 実行中status確認
agentrun status

# 最新run一覧
agentrun list-runs

# 実行前確認
agentrun validate
agentrun doctor --all
agentrun dry-run experiment --agent antigravity --repo . --goal goal.yaml "test"

# 最小実行確認
agentrun smoke-test --agent antigravity
agentrun smoke-test --agent claude
agentrun smoke-test --agent codex

# 実行後検証
agentrun verify-run .agent-runs/latest
```

---

## 34. 最終結論

本設計は、単なるdotfiles管理ではない。

```text
ai-agent-config
  = agent共通設定・rules・skills・hooksの正本

agent CLI install layer
  = uv / Antigravity / Claude Code / Codex をcontainer imageへ導入

agentrun
  = agent種類・権限レベル・資源・promptを選ぶ入口

assist
  = コーディング補助

experiment
  = capsule内で自由に自律実験

campaign
  = 長時間・複数trial・複数agent研究loop

review / multi-review
  = 複数agentによる相互レビュー

.agent-runs
  = 作業ディレクトリから見えるlive run ledger

Slurm + Apptainer
  = agent実行境界

auth bind
  = 非対話ログイン問題の解決策

hooks + supervisor
  = LLM任せにしない安全装置

validate / doctor / dry-run / smoke-test / verify-run
  = 実装と運用を壊さないための検証層
```

最初に作るべきものは以下である。

```text
1. ai-agent-config repository
2. common/AGENTS.md
3. Claude / Codex / Antigravity 用shim
4. settings / config / hooks / skills の雛形
5. uv + 3社agent CLI を入れる base-agent.def
6. install.sh によるsymlink展開
7. agentrun validate
8. agentrun doctor
9. agentrun dry-run
10. agentrun assist
11. agent選択 `--agent antigravity|claude|codex`
12. auth bind
13. .agent-runs/<run_id> と latest symlink
14. live stdout/stderr/status/command log
15. artifacts/report/patch/metrics の標準化
16. agentrun smoke-test
17. agentrun verify-run
```

その後に、`experiment`、`review`、`multi-review`、`campaign`へ段階的に広げる。