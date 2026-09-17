# USER_MANUAL

このマニュアルは、`agentrun` を使って Claude Code / Codex / Antigravity を Slurm compute node 上の Apptainer sandbox 内で実行するための利用手順です。

このリポジトリの主目的は **Slurm compute node + Apptainer sandbox で agent を安全に動かすこと** です。login node や host 上で agent CLI を直接使う運用は主経路ではありません。

## Quick Start

まず `mizuno-group/ai-agent-env` で `agentrun` を install します。

```bash
./install.sh
./install.sh --apply
```

`install.sh` は `$HOME/.local/bin/agentrun` に symlink を作ります。`$HOME/.local/bin` が `PATH` に入っていれば、以後はパスなしで `agentrun` を実行できます。

### Image ビルド（初回必須）

`.sif` は git 管理外のため、各ユーザーが compute node でビルドする必要があります。`runtime/apptainer/base-agent.sif` が存在しない場合、`doctor` は `[FAIL]` を出し、agent を起動できません。

```bash
runtime/apptainer/build-images.sh [--force] [system|agent]                                # dry-run（確認のみ）
srun --partition <partition> runtime/apptainer/build-images.sh --run                      # 両方ビルド（必要な層だけ）
srun --partition <partition> runtime/apptainer/build-images.sh --run --force              # 両方を強制再ビルド
srun --partition <partition> runtime/apptainer/build-images.sh --run --force agent        # agent 層のみ強制再ビルド
```

`base-system.sif` → `base-agent.sif` の順にビルドされます。ダウンロードを含むため数十分かかります。

`--force` なしの場合、既存の `.sif` は次のときだけ作り直されます。それ以外は `reusing existing ...` と表示して再利用します。

- `.def` の更新日時が `.sif` より新しい（`git pull` で `.def` が更新された場合など）
- agent 層のみ: `base-system.sif` が `base-agent.sif` より新しい

判定は更新日時だけなので、`.def` を変えずに中身を新しくしたいときは `--force` を使います。代表例は agent CLI のバージョンアップです。CLI は build 時に install script で最新版を取得するため、`--run --force agent` で `base-system.sif` の再ビルドをスキップしつつ agent 層だけ作り直せます。`build-images.sh` は `SLURM_JOB_ID` が設定されていない環境（login node）での実行を拒否します。

ビルド完了後、以下で状態を確認します。

```bash
agentrun agents
agentrun validate
agentrun doctor --agent <name>   # 使用する agent を指定する（例: claude, codex, antigravity）
```

`doctor` の `image:base-agent.sif` が `[OK]` になれば準備完了です。

### 認証情報のセットアップ（初回必須）

`agentrun` は各 agent の認証情報を `$HOME/.agentrun/auth/<agent>/`（auth store）に管理します。

**推奨: `auth login`** を使うと、host 上での agent ログインと store へのインポートを一括で実行します。

```bash
agentrun auth login --agent claude
agentrun auth login --agent codex
agentrun auth login --agent antigravity   # agy を対話起動して認証後 /exit
agentrun auth status
```

全 agent をまとめてログイン・インポートする場合:

```bash
agentrun auth login --all
agentrun auth status
```

`auth login` が使用する host 側 CLI (`claude`, `codex`, `agy`) は `$PATH` に存在する必要があります。インストール先の例: `$HOME/.local/bin/`

**既に host 側でログイン済みの場合** は `auth import` のみ実行します。

```bash
agentrun auth import --agent claude
agentrun auth status --agent claude
```

`auth import` がコピーするファイルは以下の通りです。

```text
claude      $HOME/.claude/.credentials.json
            $HOME/.claude.json
codex       $HOME/.codex/auth.json
antigravity $HOME/.gemini/antigravity-cli/antigravity-oauth-token
            $HOME/.gemini/antigravity-cli/installation_id
```

以後のジョブは store から認証情報を staging します。host 側の元ファイルは参照されません（store に存在しない場合のみ fallback します）。

store をリセットして再インポートする場合:

```bash
agentrun auth reset --agent codex
agentrun auth login --agent codex
```

Codex を対話式に起動する例:

```bash
agentrun dry-run assist --agent codex --partition <partition> --show-mounts
agentrun assist --agent codex --partition <partition>
```

TTY が不要な batch 実行にする場合:

```bash
agentrun assist --submit --agent codex --partition <partition> "Hello"
```

`<partition>` は利用環境の Slurm partition 名に置き換えてください。毎回 `--partition` を書きたくない場合は、環境変数 `AGENTRUN_SLURM_PARTITION` に設定できます。

```bash
export AGENTRUN_SLURM_PARTITION=<partition>
agentrun assist --agent codex
```

`AGENTRUN_SLURM_PARTITION` も `--partition` も指定しない場合、`agentrun` は partition 指定を Slurm に渡しません。その場合は cluster 側の default partition に従います。

デフォルトの job time は profile ごとに決まります。

```text
assist        01:00:00
review        01:00:00
multi-review  02:00:00
experiment    08:00:00
campaign      08:00:00
smoke-test    00:10:00
```

時間を変える場合は `--time HH:MM:SS` を指定します。

```bash
agentrun assist --agent codex --partition <partition> --time 02:00:00
```

### Secrets（トークン系の環境変数）のセットアップ（任意）

Hugging Face のトークンなど、capsule 内で環境変数として使いたい値は `secrets/.env` に書きます。GitHub のトークンはここには書かず、次節の [GitHub CLI broker](#github-cli-broker任意) を使ってください。

```bash
./install.sh --apply        # secrets/.env と secrets/gh.env が無ければ template から作成（chmod 600）
$EDITOR secrets/.env        # 使う行のコメントを外して値を入れる
agentrun doctor --agent claude
```

`secrets/.env` は gitignore 済みです。template（`secrets/.env.example`）は全行コメントアウトされた状態で、以下の入力欄があります。`agentrun` の初回 run 時にも、無ければ自動で作成されます。

```text
# HF_TOKEN=     huggingface_hub / hf CLI が自動で使用（hf auth login 不要）
```

書式は `KEY=VALUE` を 1 行に 1 つです。上記以外の変数も同じ書式で追加できます。

渡し方と見え方:

- 値は `apptainer exec --env-file <path>` で渡されます。file は job 実行時に compute node 上で apptainer が読みます。
- file 自体は container に mount されません（capsule に mount されるのは `common/hooks` と `common/skills` だけです）。
- `apptainer_exec.sh`、`submit.sbatch`、`capsule.yaml`、dry-run の出力には、file の path と変数名だけが出て、値は書かれません。
- **環境変数になった値は agent から読めます**（`env`、`/proc/self/environ` など）。隠せるのは file と run の記録だけです。トークンは権限を絞り、有効期限を付けてください。
  - Hugging Face: fine-grained token、読み取り専用（gated model の取得なら public gated repos の read のみ）。public（非 gated）な model / dataset の download にトークンは不要です
- `secrets/.env` に `GH_TOKEN` を書くと、トークンが agent に直接渡るため warning が出ます。`secrets/gh.env` に移してください。

別の file を使う場合や、secrets を渡さない場合:

```bash
agentrun assist --agent claude --secrets-file /path/to/other.env
agentrun assist --agent claude --no-secrets
export AGENTRUN_SECRETS_FILE=/path/to/other.env   # 常に別 file を使う
```

注意:

- file が group / others から読める場合は warning が出ます（`chmod 600` してください）。
- `--repo` や `--bind` の mount 元に secrets file が含まれると、`/workspace` などから agent に見えてしまうため warning が出ます。`slurm-agents-capsule` 自体を `--repo` にして起動する場合（`--repo` を省略してこの directory で実行した場合も含む）が該当します。

### GitHub CLI broker（任意）

agent に GitHub の認証情報を一切渡さずに、許可した `gh` コマンドだけを使わせる仕組みです。

```bash
./install.sh --apply        # secrets/gh.env が無ければ template から作成（chmod 600）
$EDITOR secrets/gh.env      # GH_TOKEN= のコメントを外して値を入れる
agentrun doctor --agent claude   # gh-broker:token が [OK] になることを確認
```

`secrets/gh.env` に `GH_TOKEN` が設定されていると、すべての run で broker が起動します。run ごとに止める場合は `--no-gh-broker` を付けます。

仕組み:

- `apptainer_exec.sh` は agent の capsule より先に、**別の apptainer container** で broker（`runtime/gh-broker/gh_broker.py`）を起動します。`GH_TOKEN` は `--env-file secrets/gh.env` でこの container にだけ渡ります。
- agent の capsule では `/usr/local/bin/gh` が `runtime/gh-broker/gh-client` に置き換わります。client は command を Unix socket（compute node の `/tmp/agentrun-gh.*`、capsule 内では `/opt/gh-broker/gh.sock`）で broker に送り、結果を受け取るだけです。
- `--containall` により 2 つの container は PID namespace が分かれているため、agent から broker の process や環境変数は見えません。`secrets/gh.env` もどちらの capsule にも mount されません。
- broker は `runtime/gh-broker/allowlist.txt` にある subcommand だけを実行します。既定は `issue list/view/create/comment/edit/close/reopen/status`、`pr list/view/diff/checks/status/comment`、`search issues/prs`、`repo view`、`label list` です。`auth`、`api`、`extension` などは拒否されます。
- 対象 repository は `-R`/`--repo`、`GH_REPO`、または capsule 内 git repository の `origin` remote から client が判定し、`OWNER/REPO` として broker に渡します。broker は空の作業 directory で `gh` を実行し、agent が書き換えられる git 設定を読みません。
- `--body-file`/`-F` のファイルは client が読んで stdin で送ります。broker 側でパスを開くことはありません。`--recover` は拒否されます。
- broker の返す出力とログからは、トークン文字列を `***` に置き換えます。実行・拒否したコマンドは `live/gh_broker.log` に記録されます（トークンは含みません）。
- run が終わると broker は停止し、socket directory は削除されます。

制限と注意:

- 対話的な操作（prompt、`--web`、`--editor`）は使えません。issue / PR 番号は明示してください（現在の branch からの推定は broker 側ではできません）。
- agent は許可リストの範囲内でなら `gh` を自由に使えます（issue の大量作成など）。許可リストとトークンの権限（例: Issues: Read and write、Pull requests: Read、Metadata: Read、対象 repository のみ）の両方で絞ってください。
- capsule 内の `/usr/bin/gh` を直接呼ぶことはできますが、認証情報が無いため認証の必要な操作は失敗します。
- `gh` は image（`base-system.def`）に入っています。`gh` 追加前にビルドした `.sif` の場合は再ビルドしてください。`git pull` で `base-system.def` が更新されていれば `build-images.sh --run` で system 層・agent 層とも作り直されます。確実に作り直す場合は `--run --force` を使います。
- 隔離は apptainer の namespace と「token file を mount しない」ことに依存しています。同じ UID で動くため、kernel の脆弱性などによる container escape までは防げません。
- `git push` の禁止（Claude の deny rule、Codex の rules、`git_branch_guard.py`）はコマンド文字列での判定で、`git -C . push` などは通ります。push の可否は、capsule に push 用の認証情報を渡さないこと、トークンの権限、remote 側の branch protection で決まります。

### 任意ディレクトリで実行した場合の挙動

`agentrun` は、コマンドを実行した host 側 current directory を基準に run directory を作ります。`--repo` を省略した場合は、その current directory 自体が container 内の `/workspace` に read/write mount されます。

例えば host 側で `/path/to/my-project` にいる状態で以下を実行した場合:

```bash
cd /path/to/my-project
agentrun assist --agent codex --partition <partition>
```

主な対応関係は以下です。

```text
host: /path/to/my-project                         -> container: /workspace:rw
host: /path/to/my-project/.agent-runs/<run_id>    -> container: /runs:rw
host: /path/to/my-project/.agent-runs/<run_id>/home    -> container: /home/sandbox
host: /path/to/my-project/.agent-runs/<run_id>/scratch -> container: /scratch:rw
host: /path/to/my-project/.agent-runs/<run_id>/cache   -> container: /cache:rw
host: <ai-agent-env repository>/common/hooks      -> container: /home/sandbox/ai-agent-config/common/hooks:ro
host: <ai-agent-env repository>/common/skills     -> container: /home/sandbox/ai-agent-config/common/skills:ro
```

`--repo` を指定した場合、`/workspace` に mount される対象だけが変わります。run directory は引き続き `agentrun` を実行した directory の `.agent-runs/<run_id>/` に作られます。

```bash
cd /path/to/run-ledger
agentrun assist --agent codex --partition <partition> --repo /path/to/my-project
```

この場合:

```text
host: /path/to/my-project                         -> container: /workspace:rw
host: /path/to/run-ledger/.agent-runs/<run_id>    -> container: /runs:rw
```

agent は全て `/workspace` に移動してから起動します。したがって、agent の process cwd と作業対象 repository は `/workspace` です。Codex では CLI 側にも `--cd /workspace` を渡します。

## Install / Uninstall

install の dry-run:

```bash
./install.sh
```

実際に symlink を作成:

```bash
./install.sh --apply
```

uninstall の dry-run:

```bash
./uninstall.sh
```

実際に symlink を削除:

```bash
./uninstall.sh --apply
```

`install.sh` / `uninstall.sh` は repository 内の設定や `.agent-runs/` を削除しません。対象は `$HOME/.local/bin/agentrun` の symlink だけです。

## 基本概念

`agentrun` は、agent 固有の CLI / config / auth / hook だけを分岐し、run directory 作成、Slurm script 生成、Apptainer command 生成、status/log/verify は共通処理として扱います。

共通の container 内パス:

```text
/home/sandbox                      container home
/workspace                         作業 repository
/runs                              run ledger
/scratch                           run scratch
/cache                             run cache
/home/sandbox/ai-agent-config/common/hooks    共有 hooks（read-only）
/home/sandbox/ai-agent-config/common/skills   共有 skills（read-only）
```

config repository 全体は mount しません。mount されるのは `common/hooks` と `common/skills` だけなので、それ以外の場所に置いたファイルは container から見えません。

host 側の run directory:

```text
.agent-runs/<run_id>/
```

`dry-run` は `host_run_directory` を表示しますが、実際の directory は作成しません。副作用なしで plan を確認するためのコマンドです。

`assist` は例外的に `--submit` なしで対話式実行します。`experiment` / `campaign` / `review` / `multi-review` は `--submit` なしでは run を prepare するだけで、`sbatch` しません。

## 現在の実装範囲

実装済み:

- single-agent `assist`
- single-agent `assist --submit`
- single-agent `experiment --submit`
- single-agent `campaign --submit`
- single-agent `review --submit`
- single-agent `multi-review --submit`
- `dry-run`
- `validate`
- `doctor`
- `sync-claude`
- `sync-codex`
- `sync-antigravity`
- run status/log/list/open/verify
- smoke-test scaffold

未実装または scaffold 段階:

- 複数 agent の同時起動 orchestrator
- 相互レビューの自動実行
- `multi-review` で複数 `sbatch` を発行して結果を自動集約する処理
- `campaign` の提案を実際の training job に接続する自動制御

`--reviewers`, `--target-diff`, `--target-report`, `--agents` は現状では prompt に追記されるだけです。複数 agent の起動や出力集約は行いません。

## Agent 一覧

```bash
agentrun agents
```

利用可能な agent CLI を表示します。

例:

```text
Available agents:
  antigravity  primary   available /home/li/.local/bin/agy
  claude       secondary available /home/li/.local/bin/claude
  codex        secondary available /home/li/.local/bin/codex
```

## Validate

```bash
agentrun validate
```

以下を検証します。

- 必須ファイルの存在
- JSON / TOML の形
- hook script の executable bit
- agent 別 symlink
- hook manifest と生成済み設定の一致
- `common/hooks/*.py` が各 agent の manifest で分類済みであること

`validate` が hook の不一致を報告した場合は、該当 agent の `sync-*` を実行してから再度 `validate` します。

```bash
agentrun sync-claude
agentrun sync-codex
agentrun sync-antigravity
agentrun validate
```

## Doctor

```bash
agentrun doctor --agent claude   # 使用する agent を指定する
agentrun doctor --all            # 全 agent の auth を検証する
```

以下を確認します。

- Slurm command: `sinfo`, `squeue`, `srun`, `sbatch`
- `jq`
- agent CLI
- auth file
- image: `runtime/apptainer/base-agent.sif`
- FUSE 前提条件: host の `/dev/fuse` と、image 内の `libfuse3` / `liblzo2`
- secrets file: 存在、permission（600 か）、設定済みの変数名、current directory 配下に無いか
- GitHub CLI broker: `secrets/gh.env` の `GH_TOKEN` と permission、`secrets/.env` に `GH_TOKEN` が書かれていないか
- `.agent-runs` の書き込み可否
- git repository / branch / dirty state

FUSE のチェックは常に WARN 止まりで、run を FAIL にはしません。capsule 内で nested `apptainer exec` を
使わないなら関係がないためです。使う場合は `--allow-fuse` と合わせて Troubleshooting を参照してください。

secrets と GitHub CLI broker のチェックも WARN 止まりです。どちらも任意のためです。

login node 上で `apptainer` や `uv` が見つからない場合は WARN です。compute node や image 内で提供される構成もあるため、WARN は即失敗とは限りません。

**`--all` を指定すると 3 agent 全ての auth を検証します。**使用しない agent の auth ファイルが未設定の場合、その agent の auth チェックが `[FAIL]` になります。使用する agent だけを確認する場合は `--agent NAME` を使ってください。

auth check の対象（store ファーストで確認、store になければ host fallback）:

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
antigravity $HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/antigravity-oauth-token
            $HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/installation_id
```

store にも host にも存在しない場合のみ `[FAIL]` になります。store には `agentrun auth import --agent NAME` でインポートしてください。

## Dry Run

```bash
agentrun dry-run assist --agent codex --partition <partition> --show-mounts
```

`dry-run` は agent を起動せず、以下を表示します。

- run id
- profile
- agent
- repository path
- planned host run directory
- launch method
- Slurm command または sbatch args
- Apptainer command
- bind mounts
- prompt
- expected artifacts

`dry-run` は `.agent-runs/<run_id>/` を作成しません。表示される `host_run_directory` は予定パスです。

## Assist

対話式 assist:

```bash
agentrun assist --agent codex --partition <partition> --repo .
```

PROMPT は不要です。agent は「ユーザーの指示に従ってください」という最小限の初期コンテキストで起動し、その後はユーザーがインタラクティブに指示を与えます。PROMPT を指定した場合は無視され、警告が表示されます。

挙動:

- `srun --pty` を使う
- run directory を作成する
- auth を run home に stage する
- Apptainer 内で interactive agent CLI を起動する（初期プロンプトは最小システムコンテキストのみ）
- 終了時に `<run_dir>/home/` を削除する

TTY が必要です。TTY のない環境では `assist --submit` を使います。

`--repo` は省略可能です。省略時は current directory が `/workspace` に mount されます。

## Assist Submit

```bash
agentrun assist --submit --agent codex --partition <partition> --repo . "Your prompt"
```

挙動:

- `.agent-runs/<run_id>/` を作成する
- `submit.sbatch` を生成する
- auth を run home に stage する
- `sbatch` で投入する
- job 終了時に `<run_dir>/home/` を削除する
- `live/status.json` に `success` / `failed` を書く

agent が required artifacts を作らない場合、Slurm job が成功しても `verify-run` は失敗することがあります。特に `artifacts/report.md` は verify 対象です。

## Goal ファイル

`--goal` に渡す `goal.yaml` は、agent に与える目標の構造化定義です。

### テンプレートの生成

```bash
agentrun init-goal
```

カレントディレクトリに `goal.yaml` を生成します。`goal.yaml` が既に存在する場合はエラーになります。テンプレートの実体は `templates/goal.yaml` です。

生成されたファイルの主なフィールド:

```yaml
project: my-project          # run の識別名
mode: experiment             # assist / experiment / campaign / review / multi-review
goal:
  objective: |               # エージェントへの目標説明（自由記述）
    ...
  success_criteria:          # 達成条件リスト（agent が参照する）
    - ...
budgets:
  walltime: "01:00:00"
  cpu_cores: 2
  memory: 8G
  max_trials: 1
  max_disk_gb: 10
outputs:
  required:                  # verify-run が期待するパス
    - artifacts/report.md
    - artifacts/metrics.json
    - live/command_log.jsonl
```

`agentrun` は `goal.yaml` の内容を validate しません。フィールドは agent が参照する情報であり、`outputs.required` は verify-run の期待値として使われます（現状は agentrun 固定の required list が優先されます）。

### --goal の使い方

`--goal` を指定すると、`goal.yaml` がコンテナ内の `/runs/goal.yaml` としてアクセスできます。agent はプロンプト内の `Goal file: /runs/goal.yaml` という記述を手がかりとしてファイルを読み込みます。

```bash
agentrun init-goal
# goal.yaml を編集してから投入
agentrun experiment --submit --agent codex --partition <partition> --goal goal.yaml "Run the goal"
```

## Experiment / Campaign / Review / Multi-review

これらは profile と expected artifacts を持つ single-agent batch run です。

```bash
agentrun experiment --submit --agent codex --partition <partition> --goal tests/fixtures/goal_smoke.yaml --repo . "Run the goal"
agentrun campaign --submit --agent antigravity --partition <partition> --goal path/to/goal.yaml --repo . "Run campaign"
agentrun review --submit --agent claude --partition <partition> --target-diff path/to/diff.patch --repo . "Review this diff"
agentrun multi-review --submit --agent codex --partition <partition> --agents claude,codex,antigravity --repo . "Collect review notes"
```

重要:

- `--submit` なしでは prepare のみで、`sbatch` しません。
- `review` / `multi-review` は名前上 review 用ですが、現状は 1 agent だけを起動します。
- `--agents` は requested agents として prompt に入るだけです。
- 複数 agent を自動起動して比較・集約する機能は未実装です。

profile ごとの主な期待成果物:

```text
assist        live/status.json, live/stdout.log, artifacts/report.md, artifacts/metrics.json
experiment    assist の成果物 + live/current_task.md + artifacts/proposed_next.yaml
campaign      live/status.json, artifacts/report.md, artifacts/proposed_next.yaml, artifacts/proposed_train.sbatch
review        live/status.json, live/stdout.log, reviews/review_findings.json
multi-review  live/status.json, reviews/*.md, reviews/disagreements.json, reviews/final_recommendation.md
```

## Wizard Mode

`assist`/`experiment`/`campaign`/`review`/`multi-review` は `--partition`/`--gpus` を含めると10種類以上のフラグを組み立てる必要があり、手打ちが煩雑です。`agentrun wizard` は同じ起動ロジックへの、対話式（メニュー選択式）のフロントエンドです。

```bash
agentrun wizard
```

流れ:

1. TTY 必須（`[ -t 0 ] && [ -t 1 ]` を満たさない場合は対話せず即エラー終了）
2. UI backend を自動検出: **gum → whiptail/dialog → 標準 bash `read`/`select`** の順にフォールバックし、フォールバックする度に `"<tool> not found, falling back to <next>"` を1行 stderr に出力（インストール手順は表示しない）
3. mode → agent → launch style（assist なら「対話セッション（srun --pty）」か「バッチ投入（sbatch）」、それ以外のモードは「今すぐ sbatch するか」の confirm）→ repo → **partition**（空欄なら `AGENTRUN_SLURM_PARTITION`/cluster default）→ **GPU数** → mem/cpus/time → bind mount（「もう1つ追加しますか？」ループ）→ goal（存在しないパスは再入力を促す。`write_plan` が `cp` するため実在するファイルが必要）→ task prompt → （review なら reviewers/target-diff/target-report、multi-review なら agents リストを同じ追加ループで）の順に質問
4. `agentrun wizard --agent claude` のように一部フラグを先に渡しても、質問はスキップされず、渡された値がその項目のデフォルト値として表示されるだけです（Enter でそのまま採用可）
5. 最後に全項目のサマリを表示し、"Launch this run?" で確認。Yes ならその場で組み立てた引数で `assist`/`experiment`/`campaign`/`review`/`multi-review` と同じ起動処理（`write_plan`・auth staging・`srun --pty`/`sbatch`）を呼び出し、No なら何も実行せず終了します。

このリポジトリは `--partition`/`--gpus` が実際の CLI フラグとして存在するため、ウィザードでもそのまま対話項目に含めています。

## Run Directory

`dry-run` を除く run は `.agent-runs/<run_id>/` を作成します。

主な構成:

```text
.agent-runs/<run_id>/home/                 staged HOME
.agent-runs/<run_id>/container_config/     run 用 config copy
.agent-runs/<run_id>/prompt.txt            agent に渡す prompt
.agent-runs/<run_id>/goal.yaml             goal metadata
.agent-runs/<run_id>/apptainer_exec.sh     Apptainer command
.agent-runs/<run_id>/submit.sbatch         Slurm submit script
.agent-runs/<run_id>/live/                 status, logs, heartbeat, command log
.agent-runs/<run_id>/artifacts/            report, diff, metrics
.agent-runs/<run_id>/reviews/              review outputs
```

`.agent-runs/<run_id>/` 直下の主なファイル:

```text
capsule.yaml        run id, mode, agent, repo, goal などの run metadata
prompt.txt          agent CLI に渡す初期プロンプト（interactive assist は最小システムコンテキストのみ）
goal.yaml           --goal 指定があればその copy。未指定なら mode/agent だけの最小 metadata
apptainer_exec.sh   container を起動する実コマンド
submit.sbatch       sbatch 用 script。--submit 時はこれを投入する
```

`live/` は実行中状態とログの置き場です。

```text
live/status.json        run の最終または現在 status。初期値は {}
live/heartbeat.txt      最後に heartbeat を書いた時刻
live/current_task.md    agent または smoke が現在作業内容を書く場所。初期値は initialized
live/stdout.log         agent stdout 用 ledger。現状の batch では空のまま残ることがある
live/stderr.log         apptainer_exec.sh の stderr 追記先
live/slurm.out          Slurm stdout。submitted job の標準出力は主にここを見る
live/slurm.err          Slurm stderr
live/command_log.jsonl  command/hook 実行ログ用 JSONL（ツール名とコマンド文字列のみ、出力は含まない）。空でも異常とは限らない
live/events.jsonl       run event 用 JSONL。空でも異常とは限らない
live/exit_code.txt      Slurm job 内 command の exit code
live/slurm_job_id.txt   Slurm job id。prepare-only では空のことがある
```

`artifacts/` は agent が最終成果物を書く場所です。

```text
artifacts/report.md             人間向けの最終 report。verify-run では非空が期待される
artifacts/git_diff.patch        agent が作った diff。変更なしなら空
artifacts/metrics.json          metrics / summary metadata。初期値は {}
artifacts/environment.txt       submitted job の environment dump
artifacts/container.txt         apptainer version など container 情報
artifacts/data_manifest.txt     入出力データの manifest 用。未使用なら空
artifacts/proposed_next.yaml    experiment/campaign の次アクション提案
artifacts/proposed_train.sbatch campaign の training job 提案
```

`reviews/` は review 系 profile の出力置き場です。

```text
reviews/review_findings.json      review の構造化 findings。初期値は {}
reviews/claude.md                 Claude review 用 placeholder
reviews/codex.md                  Codex review 用 placeholder
reviews/antigravity.md            Antigravity review 用 placeholder
reviews/summary.md                review summary
reviews/disagreements.json        agent 間 disagreement 用。初期値は {}
reviews/final_recommendation.md   final recommendation
```

`home/` は container の `/home/sandbox` です。auth file や writable config はここに一時配置されます。`submit.sbatch` には cleanup trap が入っており、job 終了時に `<run_dir>/home/` は削除されます。

`scratch/` と `cache/` は run ごとの一時領域です。container 内ではそれぞれ `/scratch`, `/cache` に mount されます。

初期作成直後や prepare-only run では、空ファイル、`{}`、`initialized` だけのファイルが多く残ります。これは異常ではありません。`--submit` した job が進むにつれて `live/` と `artifacts/` が更新されます。

### 認証ストアの仕組み

agent auth file は `$HOME/.agentrun/auth/<agent>/`（store）から `<run_dir>/home/` に staging され、container には `/home/sandbox` として渡されます。host `$HOME` の auth file を直接 read/write mount する構成ではありません。store にファイルがない場合のみ host `$HOME` に fallback します。

staging 対象の auth file:

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
antigravity $HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/antigravity-oauth-token
            $HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/installation_id
```

各 agent CLI は `refresh_token` を持っているため、job 実行中に access token が期限切れになっても自動更新されます。token の期限が切れた・認証が失われた場合は、再ログインして store を更新します。

```bash
agentrun auth login --agent NAME
```

`.agent-runs/latest` は最後に prepare された run を指します。未完了 run や prepared-only run を指す場合があります。

## Run 確認

```bash
agentrun status
agentrun logs
agentrun logs --follow
agentrun tail
agentrun list-runs
agentrun open-run .agent-runs/latest
agentrun verify-run .agent-runs/latest
```

挙動:

- `status`: `.agent-runs/latest/live/status.json` を表示
- `logs`: `.agent-runs/latest/live/stdout.log` を表示
- `logs --follow`: stdout log を `tail -f`
- `tail`: `logs --follow` と同等
- `list-runs`: `.agent-runs/` 直下の run を列挙
- `open-run`: symlink を解決した run path を表示
- `verify-run`: required outputs と JSON/JSONL/status を検証

`latest` が未完了 run を指している場合、`status` が `{}` のまま正常終了したり、`verify-run` が失敗したりします。これは検出として正常です。

## Agent 差分

### Claude Code

container path:

```text
/home/sandbox/.claude/settings.json
/home/sandbox/.claude/CLAUDE.md
/home/sandbox/.claude/hooks/
/home/sandbox/.claude/skills/
```

host files:

```text
agents/claude/CLAUDE.md                    -> ../../common/AGENTS.md
agents/claude/skills                       -> ../../common/skills
agents/claude/settings.json                base config
agents/claude/settings.assist.json         assist overlay
agents/claude/settings.experiment.json     experiment overlay
agents/claude/hooks.manifest.json          hook source manifest
```

commands:

```text
interactive assist   cd /workspace && claude --dangerously-skip-permissions
batch                cd /workspace && claude --print --dangerously-skip-permissions
```

auth (store):

```text
$HOME/.agentrun/auth/claude/.claude/.credentials.json
$HOME/.agentrun/auth/claude/.claude.json
```

mounts:

```text
agents/claude/CLAUDE.md          -> /home/sandbox/.claude/CLAUDE.md:ro
container_config/settings.json   -> /home/sandbox/.claude/settings.json:ro
common/hooks                     -> /home/sandbox/.claude/hooks:ro
agents/claude/skills             -> /home/sandbox/.claude/skills:ro
```

### Codex

container path:

```text
/home/sandbox/.codex/config.toml
/home/sandbox/.codex/AGENTS.md
/home/sandbox/.codex/rules/
/home/sandbox/.codex/skills/
/etc/codex/requirements.toml
```

host files:

```text
agents/codex/AGENTS.md              -> ../../common/AGENTS.md
agents/codex/skills                 -> ../../common/skills
agents/codex/config.toml            base config（現在は [tui] のみ）
agents/codex/config.assist.toml     assist config（現在は [tui] のみ）
agents/codex/config.experiment.toml experiment config（現在は [tui] のみ）
agents/codex/hooks.manifest.json    hook source manifest
agents/codex/requirements.toml      generated managed hook config
agents/codex/rules/                 exec policy（forbidden rule のみ。allow rule は承認を飛ばす起動方法のため無意味）
```

commands:

```text
interactive assist   cd /workspace && codex --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --cd /workspace
batch                cd /workspace && codex exec --dangerously-bypass-approvals-and-sandbox --dangerously-bypass-hook-trust --skip-git-repo-check --cd /workspace
```

auth (store):

```text
$HOME/.agentrun/auth/codex/.codex/auth.json
```

mounts and staged files:

```text
agents/codex/requirements.toml       -> /etc/codex/requirements.toml:ro
agents/codex/AGENTS.md               -> /home/sandbox/.codex/AGENTS.md:ro
agents/codex/rules                   -> /home/sandbox/.codex/rules:ro
container_config/config.toml         -> <run_dir>/home/.codex/config.toml
common/skills/*                      -> <run_dir>/home/.codex/skills/* symlink
```

Codex config は run home に copy されるため writable です。trust/config persistence error が出る場合は `/home/sandbox/.codex/config.toml` が read-only bind mount になっていないか確認してください。

### Antigravity

container path:

```text
/home/sandbox/.gemini/AGENTS.md
/home/sandbox/.gemini/GEMINI.md
/home/sandbox/.gemini/config/hooks.json
/home/sandbox/.gemini/antigravity-cli/settings.json
/home/sandbox/.gemini/antigravity-cli/hooks/
/home/sandbox/.gemini/antigravity-cli/skills/
```

host files:

```text
agents/antigravity/AGENTS.md                 -> ../../common/AGENTS.md
agents/antigravity/GEMINI.md                 -> ../../common/AGENTS.md
agents/antigravity/skills                    -> ../../common/skills
agents/antigravity/settings.json             base config
agents/antigravity/settings.assist.json      assist overlay
agents/antigravity/settings.experiment.json  experiment overlay
agents/antigravity/hooks.manifest.json       hook source manifest
agents/antigravity/hooks.json                generated hook config
```

commands:

```text
interactive assist   cd /workspace && agy --dangerously-skip-permissions -i
batch                cd /workspace && agy --print --dangerously-skip-permissions
```

`agy` が見つからない場合は `antigravity`、それもなければ `gemini` に fallback します。

auth (store):

```text
$HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/antigravity-oauth-token
$HOME/.agentrun/auth/antigravity/.gemini/antigravity-cli/installation_id
```

mounts and staged files:

```text
agents/antigravity/AGENTS.md       -> /home/sandbox/.gemini/AGENTS.md:ro
agents/antigravity/GEMINI.md       -> /home/sandbox/.gemini/GEMINI.md:ro
agents/antigravity/hooks.json      -> /home/sandbox/.gemini/config/hooks.json:ro
common/hooks                       -> /home/sandbox/.gemini/antigravity-cli/hooks:ro
agents/antigravity/skills          -> /home/sandbox/.gemini/antigravity-cli/skills:ro
container_config/settings.json     -> <run_dir>/home/.gemini/antigravity-cli/settings.json
```

Antigravity の `settings.json` は `/home/sandbox/.gemini/settings.json` には bind mount しません。read-only config による書き込みエラーを避けるため、run home に copy して使います。

## Common Instructions

共通 instruction は以下を編集します。

```text
common/AGENTS.md
```

各 agent の instruction file は common file への symlink です。

```text
agents/claude/CLAUDE.md       -> ../../common/AGENTS.md
agents/codex/AGENTS.md        -> ../../common/AGENTS.md
agents/antigravity/AGENTS.md  -> ../../common/AGENTS.md
agents/antigravity/GEMINI.md  -> ../../common/AGENTS.md
```

編集後:

```bash
agentrun validate
```

## Skills Maintenance

共通 skill は以下に置きます。

```text
common/skills/
```

既存 skill の中身だけを編集する場合、通常 sync は不要です。

```bash
agentrun validate
```

skill directory を追加・削除した場合は、symlink refresh のため sync します。

```bash
agentrun sync-claude
agentrun sync-codex
agentrun sync-antigravity
agentrun validate
```

### 公開 skills の取り込み

`skills/<name>/SKILL.md` というレイアウトを持つ外部リポジトリ（ローカルパス、または GitHub URL）から、`common/skills/` へ一括で取り込めます。

```bash
# ローカルの source dir から: SOURCE_DIR/skills/ 配下の全サブディレクトリを取り込み（SKILL.md がないものはスキップ）
agentrun skill-install ../some-skills-repo

# GitHub URL を直接渡す場合: 一時ディレクトリに shallow clone -> skills/* だけ common/skills/ へコピー -> clone を削除
agentrun skill-install https://github.com/softaworks/agent-toolkit.git

# 特定の skill だけ選んで取り込み（ローカル/URL どちらでも可）
agentrun skill-install https://github.com/softaworks/agent-toolkit.git react-dev mui

# 既に common/skills/<name> が存在する場合は上書きしない（--force で上書き）
agentrun skill-install ../some-skills-repo react-dev --force
```

URL 判定は `http(s)://`・`git@`・`ssh://`・`git://`・`*.git` のいずれかにマッチした場合で、この場合のみ `git clone --depth 1` を一時ディレクトリに対して行い、コピー完了後に即座に削除します（`common/skills/` にはクローン全体ではなく `skills/*` の中身だけが残ります）。取り込みに成功した skill が1件以上あれば、内部で `sync-claude` / `sync-codex` / `sync-antigravity` を自動実行します。取り込み後は `agentrun validate` で確認してください。

### デフォルト Skill の解説

`common/skills/` に含まれる skill とその役割を以下に示します。各 skill は `SKILL.md` として格納されており、フロントマター (`name:` / `description:`) によって agent がいつ参照すべきかを判断します。

| skill | 説明 |
| ----- | ---- |
| `uv` | Python プロジェクト・パッケージ・スクリプトの管理に使う `uv` コマンドのガイドです。`uv add`/`uv run`/`uvx` の使い分けや、venv の作成・管理方法を説明します。 |
| `agentrun-contract` | agentrun カプセル内で agent が書くべき出力ファイル・フォーマット・書き込みタイミングの一覧です。`live/status.json`・`artifacts/report.md` などの必須ファイルとモード別の追加要件、`verify-run` が何をチェックするかを記述します。 |
| `git-worktree` | git worktree の基本操作と、agentrun の `git_worktree_auto_create.py` hook によるブランチ作成時の自動 worktree 生成の挙動を説明します。コンテナ内でのパス制約（sibling ディレクトリは bind されない）についても記述します。 |
| `slurm` | カプセル内部から見える SLURM 環境変数・実行可能なコマンド（`squeue`/`sinfo`/`scontrol`）と、`sbatch`/`salloc` がブロックされる理由を説明します。代替手段として `artifacts/proposed_train.sbatch` を書く方法も記述します。 |
| `ruff` | Python ファイルを編集した後の lint・format 手順です。`post_edit_format.py` hook はフォーマッタを自動実行しないため、`uvx ruff check --fix` と `uvx ruff format` を手動実行する必要があることを説明します。 |
| `experiment-report` | `experiment`・`campaign`・`review`・`multi-review` 各モードで書くべきモード固有ファイルのスキーマです。`artifacts/proposed_next.yaml`・`artifacts/proposed_train.sbatch`・`reviews/review_findings.json`・`reviews/disagreements.json` などのフォーマットを記述します。 |
| `pytest` | `uv run pytest` を使ったテスト実行パターンと、テスト結果を `/runs/live/stdout.log` および `artifacts/metrics.json` に記録する方法を説明します。システム Python がないコンテナ環境での注意点も含みます。 |

## Hooks Maintenance

hook 実装は共通です。

```text
common/hooks/
```

ただし、どの hook をどの agent で使うかは agent ごとの manifest で管理します。

```text
agents/claude/hooks.manifest.json
agents/codex/hooks.manifest.json
agents/antigravity/hooks.manifest.json
```

既存 hook の中身だけを編集する場合:

```bash
agentrun validate
```

hook を追加・削除・リネームした場合:

```bash
agentrun sync-claude
agentrun sync-codex
agentrun sync-antigravity
agentrun validate
```

全ての `common/hooks/*.py` は、各 agent の manifest で active または ignored に分類されている必要があります。未分類 hook があると `validate` は失敗します。

全 agent の manifest は同一の event × matcher 形式を使います。

### デフォルト Hook の解説

`common/hooks/` に含まれる hook とその役割を以下に示します。

#### PreToolUse: コマンド実行フィルタ

これらは agent がコマンド実行ツール（Claude/Codex の `Bash`、Antigravity の `run_command`）を呼ぶ前に発火します。

| hook | 役割 |
| ---- | ---- |
| `block_dangerous_command.py` | `rm -rf /`・`rm -rf ~`、`mkfs`、`ssh`、`sudo` と、秘密ファイル（`.ssh/`、`id_rsa`/`id_ed25519`、`auth.json`、`.credentials.json`、`.env`/`.env.*`、`secrets/`、`.bashrc` など）へのアクセスをブロックします。判定はファイル名・パスだけで、`token`・`secret` といった単語（`AutoTokenizer`、`--max-new-tokens` など）では止めません。環境変数の値は対象外です。コマンド実行ツールとファイル系ツール（Read/Edit/Write/view_file など）の両方に適用されます。Codex の `apply_patch` は patch 本文ではなく、対象ファイルのパス（`*** Update File:` などの行）だけを判定します。 |
| `check_login_node.py` | Slurm login node 上での compute 系コマンド（`python`、`pytest`、`jupyter`、`torchrun` 等）をブロックします。`SLURM_JOB_ID` が設定されていない場合のみ動作するため、compute node 内では pass-through になります。 |
| `check_pip_forbidden.py` | `pip` の直接呼び出しと `uv pip install`/`uninstall`/`sync`/`compile` をブロックします。パッケージ管理は `uv add`/`uv remove` を使います。`uv pip list`/`show`/`freeze`/`check` は許可されます。 |
| `check_sbatch_forbidden.py` | Slurm allocation の内部（`SLURM_JOB_ID` が設定されている環境）での `sbatch`/`salloc` 呼び出しをブロックします。ネストした job 投入を防ぎます。 |
| `git_branch_guard.py` | `git merge`、`git rebase`、`git push`、`.git` ディレクトリへの直接操作をブロックします。Claude では manifest の `if: "Bash(git *)"` フィルタにより、git コマンド以外では発火しません。コマンド文字列での判定なので、`git -C . push` のような書き方や `gh pr merge`・`gh api` は止められません。push や merge を確実に防ぐには、GitHub トークンの権限と remote 側の branch protection で制限してください。 |

#### PostToolUse: コマンド実行後

コマンド実行ツールが完了した後に発火します。

| hook | 役割 |
| ---- | ---- |
| `git_worktree_auto_create.py` | `git checkout -b <branch>` または `git switch -c <branch>` の直後に、`../<branch>` に worktree を自動作成します。 |
| `update_run_status.py` | 実行されたコマンドのツール名とコマンド文字列を `live/command_log.jsonl` に追記し、`live/status.json` を更新します。コマンドの出力は記録しません（`env` の結果などから secrets の値が run directory に残るのを防ぐため）。書き込み先は `AGENTRUN_DIR`、未設定なら `/runs` です。 |

#### PostToolUse: ファイル編集後

ファイル編集ツール（Claude/Codex の `Edit`/`Write`、Antigravity の `write_to_file` 等）が完了した後に発火します。

| hook | 役割 |
| ---- | ---- |
| `post_edit_format.py` | 編集イベントを `live/events.jsonl` に記録します。フォーマッタは自動実行しません。フォーマットが必要なプロジェクトでは agent 自身がコマンドとして実行するか、別 hook に追加してください。 |

#### Stop

agent セッションが終了するときに発火します。

| hook | 役割 |
| ---- | ---- |
| `stop_notify.py` | Slack Incoming Webhook で完了通知を送ります。スクリプト内の `SLACK_WEBHOOK_URL` に実際の URL を設定してください。未設定のままでも hook は失敗せず、通知をスキップします。agent 種別（Claude / Codex / Antigravity）を payload から自動検出します。 |
| `summarize_session.py` | `artifacts/report.md` が存在しない場合にプレースホルダを作成します。agent が report を出力しなかったときに `verify-run` を通過させるための最低限の保護です。 |

## Smoke Tests

`agentrun smoke-test` は、run directory と `submit.sbatch` を生成する軽量 smoke scaffold です。

prepare のみ:

```bash
agentrun smoke-test --agent codex --partition <partition>
```

Slurm に投入:

```bash
agentrun smoke-test --agent codex --partition <partition> --submit
```

この smoke test は agent の認証済み model response までは検証しません。Creator node 用の追加 helper として `assist-pty`, `codex-assist-pty`, `codex-auth` もあります。これらは container visibility、Codex writable config、authenticated `codex exec`、managed hook 発火を確認するための開発者向け Slurm test です。

## Troubleshooting

### `agentrun` が見つからない

```bash
./install.sh --apply
which agentrun
```

`$HOME/.local/bin` が `PATH` に入っていない場合は shell の設定を確認してください。

### `doctor` が auth を FAIL にする

auth store (`$HOME/.agentrun/auth/`) と host 両方にファイルが存在しない場合に FAIL になります。

```bash
agentrun auth status
agentrun auth login --agent NAME
agentrun doctor --agent NAME
```

auth file は repository に保存しません。store から `<run_dir>/home/` へ staging され、job 終了後に削除されます。

### token が期限切れ・認証エラーが出る

job の途中や次回実行時に認証エラーになった場合は、再ログインして store を更新します。

```bash
agentrun auth login --agent NAME
```

`auth login` は host CLI でのログイン（`claude auth login` / `codex login` / `agy` 対話起動）と store へのインポートを一括で実行します。

### capsule の中で `apptainer exec` が失敗する（nested apptainer / squashfuse_ll エラー）

capsule はデフォルトで FUSE を使えません。`--containall` により `/dev` が最小構成に置き換わるため、
host が `/dev/fuse` を持っていても capsule 内からは見えず、内側の `apptainer exec` が
inner `.sif` を mount できずに squashfuse_ll のエラーで落ちます。

必要な条件は 3 つで、どれが欠けても同じような失敗になります。

1. **compute node に `/dev/fuse` があること** — `agentrun doctor` が `fuse:/dev/fuse` として表示します。
   通常は `crw-rw-rw-` で全ユーザーが open できます。
2. **capsule に `/dev/fuse` が bind されていること** — `--allow-fuse` を付けます。

   ```bash
   agentrun assist --agent claude --gpus 1 --allow-fuse
   ```

   毎回付けたくない場合は `export AGENTRUN_ALLOW_FUSE=1` を shell 設定に入れてください。
   個別の run で無効化したいときは `--no-allow-fuse` を使います。
3. **image に `libfuse3` / `liblzo2` が入っていること** — squashfuse_ll がこれらに動的 link しています。
   `runtime/apptainer/base-system.def` に `libfuse3-3` `liblzo2-2` `squashfuse` `fuse3` を含めてあるので、
   image を再ビルドすれば満たされます。

   ```bash
   srun --partition <partition> runtime/apptainer/build-images.sh --run
   agentrun doctor        # fuse:image-libs が [OK] になることを確認
   ```

`base-system.def` を変更した場合は system 層と agent 層の両方を再ビルドする必要があります。
`build-images.sh` は `base-system.sif` の方が新しければ `base-agent.sif` も作り直します。
更新日時の判定で作り直されない場合（`.def` を mtime ごとコピーした場合など）は `--run --force` を使ってください。

なお `--allow-fuse` は capsule に FUSE mount 能力を与えるため、隔離をやや緩めます。
nested container を実際に必要とする run だけで有効化してください。

### `dry-run` の directory が存在しない

正常です。`dry-run` は副作用なしの plan 表示だけを行います。実体を作るには `assist`, `assist --submit`, `experiment --submit` などを実行してください。

### `status` が `{}` のまま

`.agent-runs/latest` が prepared run または未完了 run を指している可能性があります。

```bash
agentrun open-run .agent-runs/latest
agentrun verify-run .agent-runs/latest
```

### `verify-run` が `artifacts/report.md` で失敗する

agent が required artifact を作っていない状態です。Slurm job の exit code が 0 でも、run contract を満たしていなければ `verify-run` は失敗します。

### Codex trust persistence error

期待される状態:

```text
/home/sandbox/.codex/config.toml は run home 内の writable file
```

期待しない状態:

```text
/home/sandbox/.codex/config.toml:ro
```

`codex-assist-pty` smoke test で writable config を確認できます。

### Hooks が発火しない

まず mount と generated config を確認します。

```bash
agentrun dry-run assist --agent codex --show-mounts "hook check"
agentrun validate
```

Codex の実効 hook 経路は `/etc/codex/requirements.toml` です。Claude は `/home/sandbox/.claude/hooks/`、Antigravity は `/home/sandbox/.gemini/antigravity-cli/hooks/` を使います。

## Command Reference

```text
agentrun agents
agentrun validate
agentrun doctor [--agent NAME|--all]
agentrun auth login --agent NAME|--all
agentrun auth import --agent NAME|--all
agentrun auth status [--agent NAME]
agentrun auth reset --agent NAME
agentrun dry-run MODE [options] PROMPT
agentrun assist [options] [PROMPT]
agentrun assist --submit [options] PROMPT
agentrun experiment|campaign|review|multi-review [options] PROMPT
agentrun wizard [options] [PROMPT]
agentrun smoke-test [--agent NAME] [--submit]
agentrun init-goal
agentrun sync-claude
agentrun sync-codex
agentrun sync-antigravity
agentrun skill-install SOURCE_DIR|GIT_URL [SKILL_NAME...] [--force]
agentrun status
agentrun logs [--follow]
agentrun tail
agentrun list-runs
agentrun open-run [RUN_DIR]
agentrun verify-run [RUN_DIR|--run-id RUN_ID]
```

主要 option:

```text
--agent NAME              antigravity, claude, codex
--repo PATH               /workspace に mount する repository。default: .
--goal PATH               goal.yaml
--gpus N                  GPU count。default: 0
--mem SIZE                メモリ量（例: 16000M）。省略時は profile default
--cpus N                  CPU コア数。省略時は profile default
--time HH:MM:SS           walltime override。省略時は profile default
--partition NAME          Slurm partition。省略時は AGENTRUN_SLURM_PARTITION、未設定なら cluster default
--bind SRC:DST[:OPTIONS]  追加 bind mount（複数指定可）。OPTIONS: ro|rw
--allow-fuse              /dev/fuse を capsule に bind する（nested apptainer / FUSE mount 用）。
                          default: off。AGENTRUN_ALLOW_FUSE=1 で常時 on にもできる
--no-allow-fuse           AGENTRUN_ALLOW_FUSE=1 が設定されていても off に強制する
--secrets-file PATH       PATH の KEY=VALUE を capsule に環境変数として渡す。
                          default: secrets/.env（存在する場合）。AGENTRUN_SECRETS_FILE でも指定可
--no-secrets              secrets file を渡さない
--no-gh-broker            secrets/gh.env に GH_TOKEN があっても GitHub CLI broker を起動しない
--reviewers LIST          prompt に追記される reviewer list
--target-diff PATH        prompt に追記される review target diff
--target-report PATH      prompt に追記される review target report
--agents LIST             prompt に追記される requested agents
--show-mounts             dry-run で agent 固有 mount も表示
--submit                  prepare 後に sbatch する
```
