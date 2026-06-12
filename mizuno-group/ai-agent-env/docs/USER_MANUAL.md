# [claude code]

この章では `agentrun` の Claude Code 側だけを説明します。

## スコープ

このリポジトリは、Slurm の compute node 上で Apptainer sandbox 内に Claude Code を起動するためのものです。host 上で Claude Code を直接使う運用は主経路ではありません。

Claude Code run では以下のパスを使います。

- host 側 config root: `mizuno-group/ai-agent-env`
- container 側 config root: `/home/sandbox/ai-agent-config`
- container home: `/home/sandbox`
- workspace: `/workspace`
- run ledger: `/runs`
- Claude Code config: `/home/sandbox/.claude/settings.json`
- Claude Code hooks: `/home/sandbox/.claude/hooks/`
- Claude Code skills: `/home/sandbox/.claude/skills/`

## クイックスタート

`mizuno-group/ai-agent-env` から実行します。

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun doctor --agent claude
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator --show-mounts "Hello"
./runtime/agentrun/agentrun assist --agent claude --partition small-creator "Hello"
```

`--partition small-creator` は test site 用の例です。product script に partition 名を hard-code しないでください。

## 基本コマンド

### Agent 一覧

```bash
./runtime/agentrun/agentrun agents
```

現在の環境で `claude` が利用可能か確認します。

### 設定検証

```bash
./runtime/agentrun/agentrun validate
```

必須ファイル、JSON の形、hook の executable bit、symlink の整合性を検証します。

Claude Code については、追加で以下を確認します。

- `agents/claude/hooks.manifest.json` が存在し、形式が正しいこと。
- active hook がすべて `common/hooks/` に存在し、実行可能であること。
- すべての `common/hooks/*.py` が manifest に分類されていること。
- `settings.json` の `.hooks` セクションが manifest から生成した内容と一致すること。
- `agents/claude/CLAUDE.md -> ../../common/AGENTS.md` であること。
- `agents/claude/skills -> ../../common/skills` であること。

### Doctor

```bash
./runtime/agentrun/agentrun doctor --agent claude
```

Slurm command、Apptainer、Claude Code CLI、image など、ローカル実行に必要な前提を確認します。

### Dry Run

```bash
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator --show-mounts "Hello"
```

run directory のパス（host_run_directory）を計算・表示し、Claude Code は起動せずに、予定される Slurm command と Apptainer command を表示します。

本番実行前に以下を確認する用途で使います。

- どの repo が `/workspace` に mount されるか。
- `settings.json` がどのファイルから生成されるか（assist か base か）。
- `common/hooks` が `/home/sandbox/.claude/hooks` に mount されるか。
- `assist` が interactive な `claude` を使うか。
- `assist --submit` が `claude --print` を使うか。

### 対話式 Assist

```bash
./runtime/agentrun/agentrun assist --agent claude --partition small-creator --repo . "Your prompt"
```

挙動:

- `srun --pty` を使います。
- Apptainer 内で interactive な `claude` を起動します。
- `--dangerously-skip-permissions` を付けます。
- `settings.assist.json` と `settings.json` を jq でマージした設定が使われます。
- assist モードでは `/runs/live/` の更新は行われません（terminal が live view になります）。
- run 終了後に `<run_dir>/home/` が自動削除されます。

`--repo` は省略可能です。省略した場合は current directory が使われます。

### Submit する Assist

```bash
./runtime/agentrun/agentrun assist --submit --agent claude --partition small-creator --repo . "Your prompt"
```

挙動:

- `.agent-runs/<run_id>/` を生成します。
- `sbatch` で Slurm job を投入します。
- `claude --print --dangerously-skip-permissions` を使います（non-interactive）。
- auth credentials を run home に stage します。
- job 終了時に `<run_dir>/home/` を削除します。
- job 終了後に `live/status.json` に `success` / `failed` を書き込みます。

### Experiment

```bash
./runtime/agentrun/agentrun experiment --submit --agent claude --partition small-creator --goal path/to/goal.yaml --repo . "Run the goal"
```

挙動:

- batch execution を使います。
- 存在する場合は `agents/claude/settings.experiment.json` を `settings.json` とマージした設定を使います。
- `experiment` モードでは `git push` と `sbatch` が deny に追加されます。

## Run Directory

各 run は `.agent-runs/<run_id>/` を作成します。

重要なパス:

```text
.agent-runs/<run_id>/home/                 /home/sandbox 用の staged HOME
.agent-runs/<run_id>/home/.claude/         staged Claude Code home
.agent-runs/<run_id>/container_config/     モード別にマージ済みの settings.json
.agent-runs/<run_id>/prompt.txt            Claude Code に渡される prompt
.agent-runs/<run_id>/apptainer_exec.sh     生成された Apptainer command
.agent-runs/<run_id>/submit.sbatch         生成された Slurm submit script
.agent-runs/<run_id>/live/                 slurm.out, slurm.err, status.json
.agent-runs/<run_id>/artifacts/            report, diff, metrics
```

便利な確認コマンド:

```bash
./runtime/agentrun/agentrun status
./runtime/agentrun/agentrun logs [--follow]
./runtime/agentrun/agentrun tail
./runtime/agentrun/agentrun list-runs
./runtime/agentrun/agentrun open-run .agent-runs/latest
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

## Claude Code の Mount 構成

Claude Code run では、`agentrun` は以下を mount します。

```text
<run_dir>/home                             -> /home/sandbox
<repo>                                     -> /workspace:rw
<run_dir>                                  -> /runs:rw
<run_dir>/scratch                          -> /scratch:rw
<run_dir>/cache                            -> /cache:rw
<ai-agent-env>                             -> /home/sandbox/ai-agent-config:ro
agents/claude/CLAUDE.md                    -> /home/sandbox/.claude/CLAUDE.md:ro
<container_config>/settings.json           -> /home/sandbox/.claude/settings.json:ro
common/hooks                               -> /home/sandbox/.claude/hooks:ro
agents/claude/skills                       -> /home/sandbox/.claude/skills:ro
```

`<container_config>/settings.json` は run ごとに生成されます。assist モードでは `settings.json` + `settings.assist.json` を jq でマージしたものが使われます。他のモードも同様に mode overlay が存在する場合はマージされます。

hook script は `common/hooks/` から直接 mount されます。`settings.json` の hooks 参照パスは `~/.claude/hooks/...` 形式で、container 内ではこの mount 先に解決されます。

## Claude Code 設定ファイル

Claude Code 固有ファイルは `agents/claude/` 以下にあります。

```text
agents/claude/CLAUDE.md                    ../../common/AGENTS.md への symlink
agents/claude/skills                       ../../common/skills への symlink
agents/claude/settings.json               Claude Code base config（hooks セクションは manifest から生成）
agents/claude/settings.assist.json        assist モード用 permissions overlay
agents/claude/settings.experiment.json    experiment モード用 permissions overlay
agents/claude/hooks.manifest.json         hook 分類の source manifest
```

container run における実効設定は `<run_dir>/container_config/settings.json` です（base + mode overlay のマージ結果）。

`settings.json` の hooks セクションは `hooks.manifest.json` から `sync-claude` で生成されます。permissions・env 等の他のキーは `sync-claude` では変更されません。

## Common Instructions のメンテナンス

編集対象:

```text
common/AGENTS.md
```

`agents/claude/CLAUDE.md` は symlink であるため、追加編集は不要です。run 時に `/home/sandbox/.claude/CLAUDE.md` に mount されます。

編集後は以下を実行します。

```bash
./runtime/agentrun/agentrun validate
```

## Skills のメンテナンス

skills は以下で編集または追加します。

```text
common/skills/
```

既存 skill の中身だけを編集する場合、sync は不要です。`agents/claude/skills` は `common/skills` への symlink であり、container 内に直接 mount されます。

skill directory を追加または削除した場合は、symlink が正しいことを確認するために以下を実行します。

```bash
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

## Hooks のメンテナンス

hook 実装は以下に置きます。

```text
common/hooks/
```

Claude Code の hook 分類は以下に置きます。

```text
agents/claude/hooks.manifest.json
```

manifest の構造:

```json
{
  "hooks": [
    {
      "event": "PreToolUse",
      "matcher": "Bash",
      "entries": [
        {"script": "block_dangerous_command.py"},
        {"script": "git_branch_guard.py", "if": "Bash(git *)"}
      ]
    },
    ...
  ],
  "ignored": []
}
```

各エントリの説明:

| フィールド | 説明 |
|---|---|
| `event` | フック発火イベント。`PreToolUse` / `PostToolUse` / `PermissionRequest` / `Stop` |
| `matcher` | ツール名フィルタ。`Bash` / `Read` / `Edit\|Write\|NotebookEdit` / `""`（空=全ツール） |
| `entries[].script` | `common/hooks/` 内のスクリプトファイル名 |
| `entries[].if` | オプション。matcher 内のさらに細かいフィルタ条件 (`Bash(git *)` 形式) |
| `ignored` | `common/hooks/` に存在するが Claude Code では使わないスクリプトのリスト |

Codex の manifest（`pre_command` / `post_command` 2分類）と異なり、Claude Code は event × matcher の2軸構造を持ちます。

### 既存 Hook の中身だけを編集する場合

既存の `common/hooks/*.py` の中身だけを編集する場合、生成ファイルの更新は不要です。

```bash
./runtime/agentrun/agentrun validate
```

hook script は `common/hooks/` から直接 mount されるため、新しい run では更新後の script が即座に使われます。

### Hook の追加・削除・リネーム

`common/hooks/` を更新した後、`agents/claude/hooks.manifest.json` を更新します。

すべての `common/hooks/*.py` は `hooks[].entries` または `ignored` のいずれかに分類する必要があります。event と matcher はスクリプトの役割に基づいて手動で割り当ててください（自動推定はしません）。

その後、以下を実行します。

```bash
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

`sync-claude` は `settings.json` の `.hooks` セクションを再生成します。他のキー（permissions, env 等）は変更しません。

hook が分類されていない場合、`validate` は失敗します。

## Sync Command

```bash
./runtime/agentrun/agentrun sync-claude
```

実行内容:

1. `agents/claude/hooks.manifest.json` を検証する。
2. active hook が `common/hooks/` に存在し、実行可能であることを確認する。
3. ignored hook が `common/hooks/` に存在することを確認する。
4. 未分類の `common/hooks/*.py` があれば失敗する。
5. manifest から hooks オブジェクト JSON を生成し、`agents/claude/settings.json` の `.hooks` キーを置換する。
6. `agents/claude/CLAUDE.md -> ../../common/AGENTS.md` を refresh する。
7. `agents/claude/skills -> ../../common/skills` を refresh する。

## 認証

Claude Code auth は repository に保存しません。

host 側で期待される auth ファイル:

```text
$HOME/.claude/.credentials.json
$HOME/.claude.json
```

どちらか一方または両方が存在すれば、run 時に run home へ copy されます。

```text
<run_dir>/home/.claude/.credentials.json
<run_dir>/home/.claude.json
```

run home は run 終了後に削除されます。run-home auth は一時的な secret material として扱ってください。

## Smoke Test

```bash
tests/slurm/submit_creator_tests.sh assist-pty
```

`assist-pty` は container 可視性と assist の動作を確認します。

- interactive assist が `--print` なしの `claude` を使うこと。
- submitted assist が `claude --print` を使うこと。
- `CLAUDE.md` の bind-mount が `agents/claude/CLAUDE.md`（symlink）を経由していること。
- container 内で `claude --version` が成功すること。

## トラブルシューティング

### validate が hooks の不一致を報告する

`validate` が `claude-hooks-generated:agents/claude/settings.json` の FAIL を報告した場合、manifest と `settings.json` の hooks セクションが乖離しています。

以下を実行します。

```bash
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

### 新しい Hook で validate が失敗する

`validate` が `claude-hooks-unclassified` を報告した場合、`agents/claude/hooks.manifest.json` の `hooks` または `ignored` に追加してください。

その後:

```bash
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

### Hooks が発火しない

まず dry-run で mount 構成を確認します。

```bash
./runtime/agentrun/agentrun dry-run assist --agent claude --show-mounts "hook check"
```

Apptainer command に以下が含まれている必要があります。

```text
common/hooks:/home/sandbox/.claude/hooks:ro
```

次に、settings.json の hooks セクションが正しく生成されているか確認します。

```bash
jq '.hooks' agents/claude/settings.json
./runtime/agentrun/agentrun validate
```

hook script の参照パスは `~/.claude/hooks/...` 形式である必要があります。`/home/sandbox/...` などの絶対パスになっていないか確認してください。

### 認証エラー

container 内で Claude Code の認証に失敗した場合、以下を確認します。

```bash
ls -la "$HOME/.claude/.credentials.json" "$HOME/.claude.json"
./runtime/agentrun/agentrun doctor --agent claude
```

認証ファイルが存在する場合、run home に正しく copy されたか確認します。

```bash
ls -la .agent-runs/latest/home/.claude/
```

## 通常メンテナンスのチェックリスト

common instructions を編集する場合:

```bash
vim common/AGENTS.md
./runtime/agentrun/agentrun validate
```

common skill を編集する場合:

```bash
vim common/skills/<skill>/SKILL.md
./runtime/agentrun/agentrun validate
```

common skill を追加または削除する場合:

```bash
mkdir -p common/skills/<skill>
vim common/skills/<skill>/SKILL.md
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

hook を編集する場合:

```bash
vim common/hooks/<hook>.py
./runtime/agentrun/agentrun validate
```

hook を追加・削除・リネームする場合:

```bash
vim common/hooks/<hook>.py
vim agents/claude/hooks.manifest.json   # event/matcher を指定して追記 or 削除
./runtime/agentrun/agentrun sync-claude
./runtime/agentrun/agentrun validate
```

permissions / env など hooks 以外の設定を変更する場合:

```bash
vim agents/claude/settings.json         # hooks キー以外を直接編集（sync-claude は不要）
./runtime/agentrun/agentrun validate
```

assist / experiment モードの追加制限を変更する場合:

```bash
vim agents/claude/settings.assist.json
vim agents/claude/settings.experiment.json
./runtime/agentrun/agentrun validate
```

利用前に確信度を上げたい場合:

```bash
./runtime/agentrun/agentrun dry-run assist --agent claude --partition small-creator --show-mounts "smoke"
tests/slurm/submit_creator_tests.sh assist-pty
```

---

# [codex]

この章では `agentrun` の Codex 側だけを説明します。Antigravity と Claude Code の章は、それぞれの担当エージェントが後から追記する想定です。

## スコープ

このリポジトリは、Slurm の compute node 上で Apptainer sandbox 内に agent を起動するためのものです。host 上で Codex を直接使う運用は主経路ではありません。

Codex run では以下のパスを使います。

- host 側 config root: `mizuno-group/ai-agent-env`
- container 側 config root: `/home/sandbox/ai-agent-config`
- container home: `/home/sandbox`
- workspace: `/workspace`
- run ledger: `/runs`
- Codex managed hooks: `/etc/codex/requirements.toml`

現在の構成には `common/codex/` は存在しません。

## クイックスタート

`mizuno-group/ai-agent-env` から実行します。

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun doctor --agent codex
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator --show-mounts "Hello"
./runtime/agentrun/agentrun assist --agent codex --partition small-creator "Hello"
```

`--partition small-creator` は test site 用の例です。product script に partition 名を hard-code しないでください。

## 基本コマンド

### Agent 一覧

```bash
./runtime/agentrun/agentrun agents
```

現在の環境で `codex` が利用可能か確認します。

### 設定検証

```bash
./runtime/agentrun/agentrun validate
```

必須ファイル、JSON/TOML の形、hook の executable bit、symlink、Codex の生成ファイルを検証します。

Codex については、追加で以下を確認します。

- `agents/codex/hooks.manifest.json` が存在し、形式が正しいこと。
- active hook がすべて `common/hooks/` に存在し、実行可能であること。
- すべての `common/hooks/*.py` が active または ignored として分類されていること。
- `agents/codex/hooks.json` が manifest から生成された内容と一致すること。
- `agents/codex/requirements.toml` が manifest から生成された内容と一致すること。
- `agents/codex/AGENTS.md -> ../../common/AGENTS.md` であること。
- `agents/codex/skills -> ../../common/skills` であること。

### Doctor

```bash
./runtime/agentrun/agentrun doctor --agent codex
```

Slurm command、Apptainer、Codex CLI、image など、ローカル実行に必要な前提を確認します。

### Dry Run

```bash
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator --show-mounts "Hello"
```

run directory のパス（host_run_directory）を計算・表示し、Codex は起動せずに、予定される Slurm command と Apptainer command を表示します。

本番実行前に以下を確認する用途で使います。

- どの repo が `/workspace` に mount されるか。
- どの run directory が `/runs` に mount されるか。
- `/etc/codex/requirements.toml` が mount されるか。
- `assist` が interactive な top-level `codex` を使うか。
- `assist --submit` が non-interactive な `codex exec` を使うか。

### 対話式 Assist

```bash
./runtime/agentrun/agentrun assist --agent codex --partition small-creator --repo . "Your prompt"
```

挙動:

- `srun --pty` を使います。
- Apptainer 内で interactive な top-level `codex` を起動します。
- `--cd /workspace` を指定します。
- Slurm + Apptainer が外側の sandbox なので、`--dangerously-bypass-approvals-and-sandbox` を付けます。
- `--dangerously-bypass-hook-trust` を付けます。managed hooks 自体は `/etc/codex/requirements.toml` によって制御されます。

`--repo` は省略可能です。省略した場合は current directory が使われます。

### Submit する Assist

```bash
./runtime/agentrun/agentrun assist --submit --agent codex --partition small-creator --repo . "Your prompt"
```

挙動:

- `.agent-runs/<run_id>/` を生成します。
- `sbatch` で Slurm job を投入します。
- non-interactive な `codex exec` を使います。
- Codex config と auth を run home に stage します。
- 生成された job script に cleanup trap が入っている場合、job 終了時に staged home material を削除します。

interactive TUI が不要な場合に使います。

### Experiment

```bash
./runtime/agentrun/agentrun experiment --submit --agent codex --partition small-creator --goal path/to/goal.yaml --repo . "Run the goal"
```

挙動:

- batch execution を使います。
- 存在する場合は `agents/codex/config.experiment.toml` を使います。
- `codex exec` を使います。
- `assist` と同じ Codex common config と managed hooks を mount します。

## Run Directory

各 run は `.agent-runs/<run_id>/` を作成します。

重要なパス:

```text
.agent-runs/<run_id>/home/                 /home/sandbox 用の staged HOME
.agent-runs/<run_id>/home/.codex/          staged Codex home
.agent-runs/<run_id>/container_config/     run ごとに選択された config copy
.agent-runs/<run_id>/prompt.txt            Codex に渡される prompt
.agent-runs/<run_id>/goal.yaml             goal metadata
.agent-runs/<run_id>/apptainer_exec.sh     生成された Apptainer command
.agent-runs/<run_id>/submit.sbatch         生成された Slurm submit script
.agent-runs/<run_id>/live/                 stdout, stderr, status, heartbeat, command log
.agent-runs/<run_id>/artifacts/            report, diff, metrics
```

便利な確認コマンド:

```bash
./runtime/agentrun/agentrun status
./runtime/agentrun/agentrun logs --follow
./runtime/agentrun/agentrun tail
./runtime/agentrun/agentrun list-runs
./runtime/agentrun/agentrun open-run .agent-runs/latest
./runtime/agentrun/agentrun verify-run .agent-runs/latest
```

## Codex の Mount 構成

Codex run では、`agentrun` は以下を mount します。

```text
<run_dir>/home                       -> /home/sandbox
<repo>                               -> /workspace:rw
<run_dir>                            -> /runs:rw
<run_dir>/scratch                    -> /scratch:rw
<run_dir>/cache                      -> /cache:rw
<ai-agent-env>                       -> /home/sandbox/ai-agent-config:ro
agents/codex/requirements.toml       -> /etc/codex/requirements.toml:ro
agents/codex/AGENTS.md               -> /home/sandbox/.codex/AGENTS.md:ro
agents/codex/rules                   -> /home/sandbox/.codex/rules:ro
```

選択された Codex の `config*.toml` は以下に copy されます。

```text
<run_dir>/home/.codex/config.toml -> /home/sandbox/.codex/config.toml
```

このファイルは container 内で writable です。そのため、Codex は read-only な repository mount に書き込まずに runtime trust/config state を保存できます。

common skills は以下に link されます。

```text
<run_dir>/home/.codex/skills/<skill_name> -> /home/sandbox/ai-agent-config/common/skills/<skill_name>
```

## Codex 設定ファイル

Codex 固有ファイルは `agents/codex/` 以下にあります。

```text
agents/codex/AGENTS.md              ../../common/AGENTS.md への symlink
agents/codex/skills                 ../../common/skills への symlink
agents/codex/config.toml            Codex base config
agents/codex/config.assist.toml     assist 用 config
agents/codex/config.experiment.toml experiment 用 config
agents/codex/hooks.manifest.json    hook 分類の source manifest
agents/codex/hooks.json             生成された通常の Codex hook JSON
agents/codex/requirements.toml      container で使う生成済み managed hook config
agents/codex/rules/                 Codex 固有の exec policy
```

container run における実効 hook config は `agents/codex/requirements.toml` です。これは `/etc/codex/requirements.toml` に mount されます。

`agents/codex/hooks.json` は確認と将来互換性のために生成していますが、検証済みの実行経路は `/etc/codex/requirements.toml` 経由の managed hooks です。

## Common Instructions のメンテナンス

編集対象:

```text
common/AGENTS.md
```

通常、Codex 固有の追加編集は不要です。`agents/codex/AGENTS.md` は common file への symlink であり、run 時には `/home/sandbox/.codex/AGENTS.md` に mount されます。

編集後は以下を実行します。

```bash
./runtime/agentrun/agentrun validate
```

## Skills のメンテナンス

skills は以下で編集または追加します。

```text
common/skills/
```

既存 skill の中身だけを編集する場合、通常 Codex 固有の sync は不要です。Codex run home は `common/skills` に直接 link します。

skill directory を追加または削除した場合は、以下を実行します。

```bash
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

`sync-codex` は `agents/codex/skills` symlink を refresh します。run home は run ごとに新規作成されるため、新しい run では現在の `common/skills/*` が link されます。

## Hooks のメンテナンス

hook 実装は以下に置きます。

```text
common/hooks/
```

Codex の hook 分類は以下に置きます。

```text
agents/codex/hooks.manifest.json
```

manifest には 3 つの list があります。

```json
{
  "pre_command": [],
  "post_command": [],
  "ignored": []
}
```

使い分け:

- `pre_command`: Codex の shell/tool command の前に実行したい hook。
- `post_command`: Codex の shell/tool command の後に実行したい hook。
- `ignored`: `common/hooks/` には存在するが Codex では使わない hook。

### 既存 Hook の中身だけを編集する場合

既存の `common/hooks/*.py` の中身だけを編集する場合、通常、生成ファイルの更新は不要です。

以下を実行します。

```bash
./runtime/agentrun/agentrun validate
```

新しい Codex run では `/home/sandbox/ai-agent-config/common/hooks/...` 経由で更新後の script が使われます。

### Hook の追加・削除・リネーム

`common/hooks/` を更新した後、`agents/codex/hooks.manifest.json` を更新します。

すべての `common/hooks/*.py` は、概念上ちょうど 1 つの分類に入れる必要があります。

- `pre_command`
- `post_command`
- `ignored`

その後、以下を実行します。

```bash
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

`sync-codex` は以下を再生成します。

```text
agents/codex/hooks.json
agents/codex/requirements.toml
```

hook が分類されていない場合、`validate` は失敗します。これは silent drift を防ぐための意図的な挙動です。

### Hook 実行の確認済み経路

Codex で検証済みの hook 経路は managed hooks です。

```text
agents/codex/requirements.toml -> /etc/codex/requirements.toml
```

Slurm smoke job `3537` では、Codex の stderr に `hook: PreToolUse` と `hook: PostToolUse` が表示され、`common/hooks/update_run_status.py` が command event を以下に書き込みました。

```text
/runs/live/command_log.jsonl
```

以前の non-interactive `codex exec` smoke では通常の `~/.codex/hooks.json` は発火しませんでした。そのため、これを container hook の実効経路として扱わないでください。

## Sync Command

```bash
./runtime/agentrun/agentrun sync-codex
```

Codex の hook 分類を変更した後、または Codex symlink を refresh したい場合に使います。

実行内容:

1. `agents/codex/hooks.manifest.json` を検証する。
2. active hook が `common/hooks/` に存在し、実行可能であることを確認する。
3. ignored hook が `common/hooks/` に存在することを確認する。
4. 未分類の `common/hooks/*.py` があれば失敗する。
5. `agents/codex/hooks.json` を再生成する。
6. `agents/codex/requirements.toml` を再生成する。
7. `agents/codex/AGENTS.md -> ../../common/AGENTS.md` を refresh する。
8. `agents/codex/skills -> ../../common/skills` を refresh する。

## 認証

Codex auth は repository に保存しません。

host 側で期待される auth path:

```text
$HOME/.codex/auth.json
```

submitted Codex smoke test では、auth は run home に copy されます。

```text
<run_dir>/home/.codex/auth.json
```

Codex auth smoke test では、stage された run home は cleanup で削除されます。通常の runtime run でも、run-home auth は一時的な secret material として扱ってください。

## Smoke Test

creator test helper:

```bash
tests/slurm/submit_creator_tests.sh codex-assist-pty
tests/slurm/submit_creator_tests.sh codex-auth
```

`codex-assist-pty` は planning と container visibility を確認します。

- interactive assist が top-level `codex` を使うこと。
- submitted assist が `codex exec` を使うこと。
- Codex config が run home 内で writable であること。
- `/etc/codex/requirements.toml` が見えること。
- `AGENTS.md`、`rules`、common skills が見えること。

`codex-auth` は authenticated execution を確認します。

- container 内で `codex exec` が実行できること。
- Codex が shell command を実行できること。
- managed hooks が発火すること。
- `PostToolUse` が command を `/runs/live/command_log.jsonl` に記録すること。

## トラブルシューティング

### Trust Persistence Error

Codex が `/home/sandbox/.codex/config.toml` に trust を保存できないと報告した場合、read-only bind mount ではなく、run home に copy された writable config を使っているか確認してください。

期待される状態:

```text
<run_dir>/home/.codex/config.toml
```

期待しない状態:

```text
/home/sandbox/.codex/config.toml:ro
```

### Hooks が発火しない

まず実効 path を確認します。

```bash
./runtime/agentrun/agentrun dry-run assist --agent codex --show-mounts "hook check"
```

Apptainer command に以下が含まれている必要があります。

```text
agents/codex/requirements.toml:/etc/codex/requirements.toml:ro
```

次に以下を確認します。

```bash
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

container execution では `/home/sandbox/.codex/hooks.json` に依存しないでください。検証済みの経路は `/etc/codex/requirements.toml` です。

### 新しい Hook で Validate が失敗する

`validate` が unclassified Codex hook を報告する場合、その file name を以下のどれかに追加してください。

```text
agents/codex/hooks.manifest.json: pre_command
agents/codex/hooks.manifest.json: post_command
agents/codex/hooks.manifest.json: ignored
```

その後、以下を実行します。

```bash
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

### 認証 Smoke が失敗する

確認:

```bash
test -f "$HOME/.codex/auth.json"
tests/slurm/submit_creator_tests.sh codex-auth
```

最新 run を確認します。

```bash
./runtime/agentrun/agentrun list-runs
tail -n 100 .agent-runs/creator-codex-auth-smoke/*/live/stderr.log
cat .agent-runs/creator-codex-auth-smoke/*/live/status.json
```

## 通常メンテナンスのチェックリスト

common instructions を編集する場合:

```bash
vim common/AGENTS.md
./runtime/agentrun/agentrun validate
```

common skill を編集する場合:

```bash
vim common/skills/<skill>/SKILL.md
./runtime/agentrun/agentrun validate
```

common skill を追加または削除する場合:

```bash
mkdir -p common/skills/<skill>
vim common/skills/<skill>/SKILL.md
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

hook を編集する場合:

```bash
vim common/hooks/<hook>.py
./runtime/agentrun/agentrun validate
```

hook を追加・削除・リネームする場合:

```bash
vim common/hooks/<hook>.py
vim agents/codex/hooks.manifest.json
./runtime/agentrun/agentrun sync-codex
./runtime/agentrun/agentrun validate
```

利用前に確信度を上げたい場合:

```bash
./runtime/agentrun/agentrun dry-run assist --agent codex --partition small-creator --show-mounts "smoke"
tests/slurm/submit_creator_tests.sh codex-assist-pty
tests/slurm/submit_creator_tests.sh codex-auth
```

---

# [antigravity]

この章では `agentrun` の Antigravity (agy) 側だけを説明します。

## スコープ

このリポジトリは、Slurm の compute node 上で Apptainer sandbox 内に Antigravity を起動するためのものです。host 上で Antigravity を直接使う運用は主経路ではありません。

Antigravity run では以下のパスを使います。

- host 側 config root: `mizuno-group/ai-agent-env`
- container 側 config root: `/home/sandbox/ai-agent-config`
- container home: `/home/sandbox`
- workspace: `/workspace`
- run ledger: `/runs`
- Antigravity config: `/home/sandbox/.gemini/antigravity-cli/settings.json`
- Antigravity hooks.json: `/home/sandbox/.gemini/antigravity-cli/hooks.json`
- Antigravity hooks: `/home/sandbox/.gemini/antigravity-cli/hooks/`
- Antigravity skills: `/home/sandbox/.gemini/antigravity-cli/skills/`
- Antigravity instructions: `/home/sandbox/.gemini/AGENTS.md` および `/home/sandbox/.gemini/GEMINI.md`

## クイックスタート

`mizuno-group/ai-agent-env` から実行します。

```bash
./runtime/agentrun/agentrun validate
./runtime/agentrun/agentrun doctor --agent antigravity
./runtime/agentrun/agentrun dry-run assist --agent antigravity --partition small-creator --show-mounts "Hello"
./runtime/agentrun/agentrun assist --agent antigravity --partition small-creator "Hello"
```

`--partition small-creator` は test site 用の例です。product script に partition 名を hard-code しないでください。

## 基本コマンド

### Agent 一覧

```bash
./runtime/agentrun/agentrun agents
```

現在の環境で `antigravity` が利用可能か確認します。

### 設定検証

```bash
./runtime/agentrun/agentrun validate
```

必須ファイル、JSON の形、hook の executable bit、symlink の整合性を検証します。

Antigravity については、追加で以下を確認します。

- `agents/antigravity/hooks.manifest.json` が存在し、形式が正しいこと。
- active hook がすべて `common/hooks/` に存在し、実行可能であること。
- すべての `common/hooks/*.py` が manifest に分類されていること。
- `agents/antigravity/hooks.json` が manifest から生成した内容と一致すること。
- `agents/antigravity/AGENTS.md -> ../../common/AGENTS.md` であること。
- `agents/antigravity/GEMINI.md -> ../../common/AGENTS.md` であること。
- `agents/antigravity/skills -> ../../common/skills` であること。

### Doctor

```bash
./runtime/agentrun/agentrun doctor --agent antigravity
```

Slurm command、Apptainer、Antigravity CLI、image など、ローカル実行に必要な前提を確認します。

### Dry Run

```bash
./runtime/agentrun/agentrun dry-run assist --agent antigravity --partition small-creator --show-mounts "Hello"
```

run directory のパス（host_run_directory）を計算・表示し、Antigravity は起動せずに、予定される Slurm command と Apptainer command を表示します。

本番実行前に以下を確認する用途で使います。

- どの repo が `/workspace` に mount されるか。
- `settings.json` がどのファイルから生成されるか（assist か base か）。
- `common/hooks` が `/home/sandbox/.gemini/antigravity-cli/hooks` に mount されるか。

### 対話式 Assist

```bash
./runtime/agentrun/agentrun assist --agent antigravity --partition small-creator --repo . "Your prompt"
```

挙動:

- `srun --pty` を使います。
- Apptainer 内で interactive な `agy` (または `antigravity`) を起動します。
- `settings.assist.json` と `settings.json` を jq でディープマージした設定が使われ、`git push` や `sbatch` などの一時的な権限緩和が行われます。
- run 終了後に `<run_dir>/home/` が自動削除されます。

### Submit する Assist

```bash
./runtime/agentrun/agentrun assist --submit --agent antigravity --partition small-creator --repo . "Your prompt"
```

挙動:

- `.agent-runs/<run_id>/` を生成します。
- `sbatch` で Slurm job を投入します。
- non-interactive に実行されます。
- auth credentials を run home に stage します。
- job 終了時に `<run_dir>/home/` を削除します。

### Experiment

```bash
./runtime/agentrun/agentrun experiment --submit --agent antigravity --partition small-creator --goal path/to/goal.yaml --repo . "Run the goal"
```

挙動:

- batch execution を使います。
- 存在する場合は `agents/antigravity/settings.experiment.json` を `settings.json` とマージした設定を使います（より強力な安全制限が適用されます）。
- 初期プロンプトの先頭に自動で `/goal` が付与され、自律実行に入ります。

## Run Directory

各 run は `.agent-runs/<run_id>/` を作成します。

重要なパス:

```text
.agent-runs/<run_id>/home/                                  /home/sandbox 用の staged HOME
.agent-runs/<run_id>/home/.gemini/antigravity-cli/          staged Antigravity home
.agent-runs/<run_id>/container_config/                      モード別にマージ済みの settings.json
.agent-runs/<run_id>/prompt.txt                             Antigravity に渡される prompt
.agent-runs/<run_id>/apptainer_exec.sh                      生成された Apptainer command
.agent-runs/<run_id>/submit.sbatch                          生成された Slurm submit script
.agent-runs/<run_id>/live/                                  stdout, stderr, status.json
```

## Antigravity の Mount 構成

Antigravity run では、`agentrun` は以下を mount します。

```text
<run_dir>/home                             -> /home/sandbox
<repo>                                     -> /workspace:rw
<run_dir>                                  -> /runs:rw
<run_dir>/scratch                          -> /scratch:rw
<run_dir>/cache                            -> /cache:rw
<ai-agent-env>                             -> /home/sandbox/ai-agent-config:ro
agents/antigravity/AGENTS.md               -> /home/sandbox/.gemini/AGENTS.md:ro
agents/antigravity/GEMINI.md               -> /home/sandbox/.gemini/GEMINI.md:ro
agents/antigravity/hooks.json              -> /home/sandbox/.gemini/antigravity-cli/hooks.json:ro
common/hooks                               -> /home/sandbox/.gemini/antigravity-cli/hooks:ro
agents/antigravity/skills                  -> /home/sandbox/.gemini/antigravity-cli/skills:ro
```

設定ファイル `settings.json` は書き込みエラー（read-only file system）を防ぐため、バインドマウントではなく `<run_dir>/home/.gemini/antigravity-cli/settings.json` に **コピー** されて配置されます。
`assist` モードでは `settings.json` + `settings.assist.json` を jq でマージしたものが使われます。

## Antigravity 設定ファイル

Antigravity 固有ファイルは `agents/antigravity/` 以下にあります。

```text
agents/antigravity/AGENTS.md                    ../../common/AGENTS.md への symlink
agents/antigravity/GEMINI.md                    ../../common/AGENTS.md への symlink
agents/antigravity/skills                       ../../common/skills への symlink
agents/antigravity/settings.json                Antigravity base config
agents/antigravity/settings.assist.json         assist モード用 safety overlay
agents/antigravity/settings.experiment.json     experiment モード用 safety overlay
agents/antigravity/hooks.manifest.json          hook 分類の source manifest
agents/antigravity/hooks.json                   生成された Antigravity hook JSON
```

## Hooks のメンテナンス

hook 実装は以下に置きます。

```text
common/hooks/
```

Antigravity の hook 分類は以下に置きます。Claude Code のマニフェスト形式と全く同じ構造を持っています。

```text
agents/antigravity/hooks.manifest.json
```

manifest の構造:

```json
{
  "hooks": [
    {
      "event": "PreToolUse",
      "matcher": "Bash",
      "entries": [
        {"script": "block_dangerous_command.py"},
        {"script": "git_branch_guard.py", "if": "Bash(git *)"}
      ]
    },
    ...
  ],
  "ignored": []
}
```

### Hook の追加・削除・リネーム

`common/hooks/` を更新した後、`agents/antigravity/hooks.manifest.json` を更新します。

その後、以下を実行します。

```bash
./runtime/agentrun/agentrun sync-antigravity
./runtime/agentrun/agentrun validate
```

`sync-antigravity` は `agents/antigravity/hooks.json` を再生成します。
hook が分類されていない場合、`validate` は失敗します。

## Sync Command

```bash
./runtime/agentrun/agentrun sync-antigravity
```

実行内容:

1. `agents/antigravity/hooks.manifest.json` を検証する。
2. active hook が `common/hooks/` に存在し、実行可能であることを確認する。
3. ignored hook が `common/hooks/` に存在することを確認する。
4. 未分類の `common/hooks/*.py` があれば失敗する。
5. manifest から `agents/antigravity/hooks.json` を再生成する。
6. `agents/antigravity/AGENTS.md -> ../../common/AGENTS.md` を refresh する。
7. `agents/antigravity/GEMINI.md -> ../../common/AGENTS.md` を refresh する。
8. `agents/antigravity/skills -> ../../common/skills` を refresh する。

## 認証

Antigravity auth は repository に保存しません。

host 側で期待される auth ファイル:

```text
$HOME/.gemini/antigravity-cli/antigravity-oauth-token
$HOME/.gemini/antigravity-cli/installation_id
```

どちらか一方または両方が存在すれば、run 時に run home へ copy されます。

```text
<run_dir>/home/.gemini/antigravity-cli/antigravity-oauth-token
<run_dir>/home/.gemini/antigravity-cli/installation_id
```

run home は run 終了後に削除されます。run-home auth は一時的な secret material として扱ってください。

## トラブルシューティング

### validate が hooks の不一致を報告する

`validate` が `antigravity-hooks-generated:agents/antigravity/hooks.json` の FAIL を報告した場合、manifest と `hooks.json` が乖離しています。

以下を実行します。

```bash
./runtime/agentrun/agentrun sync-antigravity
./runtime/agentrun/agentrun validate
```

### 認証エラー

container 内で Antigravity の認証に失敗した場合、以下を確認します。

```bash
ls -la "$HOME/.gemini/antigravity-cli/antigravity-oauth-token"
./runtime/agentrun/agentrun doctor --agent antigravity
```

