# USER_MANUAL

このマニュアルは、`agentrun` を使って Claude Code / Codex を Slurm compute node 上の Apptainer sandbox 内で実行するための利用手順です。

このリポジトリの主目的は **Slurm compute node + Apptainer sandbox で agent を安全に動かすこと** です。login node や host 上で agent CLI を直接使う運用は主経路ではありません。

## Quick Start

まず `mizuno-group/ai-agent-env` で `agentrun` を install します。

```bash
./install.sh
./install.sh --apply
```

`install.sh` は `$HOME/.local/bin/agentrun` に symlink を作ります。`$HOME/.local/bin` が `PATH` に入っていれば、以後はパスなしで `agentrun` を実行できます。

### Image ビルド（初回必須）

`.sif` は git 管理外のため、各ユーザーが compute node でビルドする必要があります。`runtime/apptainer/base-system.sif` が存在しない場合、`doctor` は `[FAIL]` を出し、agent を起動できません。

```bash
runtime/apptainer/build-images.sh [--force]                                # dry-run（確認のみ）
srun --partition <partition> runtime/apptainer/build-images.sh --run                      # system image をビルド
srun --partition <partition> runtime/apptainer/build-images.sh --run --force              # system image を強制再ビルド
```

`base-system.sif` のみをビルドします。agent CLI は各ジョブの起動時に公式 installer から最新版をインストールします。バージョン更新に image の再ビルドは不要です。

`--force` なしの場合、既存の `.sif` は次のときだけ作り直されます。それ以外は `reusing existing ...` と表示して再利用します。

- `.def` の更新日時が `.sif` より新しい（`git pull` で `.def` が更新された場合など）

判定は更新日時です。強制的に image を作り直す場合は `--force` を使います。`build-images.sh` は `SLURM_JOB_ID` がない環境でのビルドを拒否します。

ビルド完了後、以下で状態を確認します。

```bash
agentrun agents
agentrun validate
agentrun doctor --agent <name>   # 使用する agent を指定する（例: claude, codex）
```

`doctor` の `image:base-system.sif` が `[OK]` になれば準備完了です。

### Rust / 日本語 LuaLaTeX

`runtime/apptainer/base-system.def` に以下を含めています。追加前にビルドした `.sif` は compute node で再ビルドしてください。

| 用途 | 導入内容 |
| --- | --- |
| Rust | rustup の build 時点の stable（minimal profile: `rustc` / `cargo` / 標準ライブラリ）、`build-essential`、`pkg-config` |
| LaTeX 組版 | `texlive-luatex`、`texlive-latex-extra`、`texlive-fonts-recommended`、`texlive-science`（`siunitx` など） |
| 日本語組版 | `texlive-lang-japanese`（LuaTeX-ja、`ltjsarticle` を含む） |
| 自動ビルド | `latexmk` |
| 文献処理 | `biber`、`texlive-bibtex-extra`（`biblatex` を含む） |
| PDF 検証・画像化 | `poppler-utils`（`pdfinfo`、`pdffonts`、`pdftotext`、`pdftoppm` など） |
| 日本語フォント | `fonts-ipaexfont`（IPAex 明朝・ゴシック）、`fontconfig` |

Rust の toolchain は `/opt/rustup`、rustup / cargo の実行ファイルは `/opt/cargo/bin` に置き、通常の capsule 起動時に `PATH` と `RUSTUP_HOME` を設定します。cargo の cache と `cargo install` の出力は run ごとの `$HOME/.cargo` に保存され、`$HOME/.cargo/bin` も `PATH` に入ります。image 内の toolchain を更新する場合は `build-images.sh --run --force` で再ビルドしてください。Rust のバージョンは build 時点の stable によって変わります。

capsule 内での確認・利用例:

```bash
rustc --version
cargo --version
cargo build --release

# LuaLaTeX を指定する。biblatex で backend=biber を使う文書では Biber も自動実行される。
latexmk -lualatex -interaction=nonstopmode -halt-on-error main.tex
pdfinfo main.pdf
pdffonts main.pdf
pdftotext main.pdf main.txt
pdftoppm -f 1 -singlefile -png -r 150 main.pdf main-page1
```

日本語文書では、例えば次のように IPAex フォントを指定できます。

```latex
\documentclass{ltjsarticle}
\usepackage[ipaex]{luatexja-preset}
\begin{document}
日本語の本文。\textsf{ゴシック体の本文。}
\end{document}
```

definition の `%test` は、空の writable HOME を使って Rust 2024 edition のプログラムを offline でコンパイル・実行し、`cargo install` の保存先も確認します。日本語明朝・ゴシックと文献を含む文書を `latexmk` + LuaLaTeX + Biber でビルドし、Poppler で PDF 情報・IPAex フォントの使用とフォント埋め込み・日本語と文献のテキスト抽出・PNG 変換を確認します。通常の image build 時に自動実行されます。既存 image に対して再実行する場合も compute node で行ってください。

```bash
srun --partition <partition> apptainer test --cleanenv --containall runtime/apptainer/base-system.sif
```

### 認証情報のセットアップ（初回必須）

`agentrun` は各 agent の認証情報を `$HOME/.agentrun/auth/<agent>/`（auth store）に管理します。

**推奨: `auth login`** を使うと、host 上での agent ログインと store へのインポートを一括で実行します。

```bash
agentrun auth login --agent claude
agentrun auth login --agent codex
agentrun auth status
```

全 agent をまとめてログイン・インポートする場合:

```bash
agentrun auth login --all
agentrun auth status
```

`auth login` が使用する host 側 CLI (`claude`, `codex`) は `$PATH` に存在する必要があります。インストール先の例: `$HOME/.local/bin/`

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
- broker は `runtime/gh-broker/allowlist.txt` に書かれた command だけを、書かれた位置引数と long flag だけで実行します。それ以外（未記載の subcommand・flag、short flag、URL、余分な位置引数）はすべて拒否します。既定の許可リストは research-harness（RDH）が発行する gh 呼び出しの全体です。

  ```text
  --version
  auth status
  repo view [repo]: --json
  issue create: --title --body-file --label --repo
  issue view <number>: --json --repo
  issue list: --state --limit --json --repo
  issue comment <number>: --body-file --repo
  issue close <number>: --comment --repo
  pr create: --title --body-file --head --base --draft --repo
  pr view <number|branch>: --json --repo
  pr list: --head --state --limit --json --repo
  pr edit <number|branch>: --body-file --repo
  ```

  書式は `<subcommand> [位置引数] : --flag ...` です。位置引数は `<number>`（Issue/PR 番号）、`<number|branch>`、`[repo]`（`OWNER/NAME`）のいずれかで、`<>` は必須、`[]` は省略可です。URL は受け付けないため、位置引数から別の repository に届くことはありません。flag の値も検証します（`--body-file` は `-` のみ、`--repo` と `repo view` の引数は `OWNER/NAME`、`--head`/`--base` は branch 名、`--state`/`--limit`/`--json` は形式）。値を取らない flag は `gh_broker.py` の `BOOLEAN_FLAGS`（既定は `--draft`）に登録されたものだけです。
- `api`（任意の GitHub API を token 付きで呼べるため）、`auth token`・`--show-token`、`issue edit`、`pr comment`、`pr merge`、`--attach` などローカルファイルを読む flag は許可しません。Issue comment の読み出しは `gh issue view <番号> --json comments` を使います（100 件を超える comment も全件返ることを確認済み）。
- **書き込み先 repository の固定**: `secrets/gh.env` の `GH_BROKER_REPOS=owner/name[,owner/name]` を設定すると、`--repo`、`repo view` の引数、client が推定した repository はこのリストに含まれる必要があります。1 つだけ書いた場合はそれが既定の対象になり、推定した repository が違っていても（fork の origin など）固定した repository に向けます。未設定の場合は token が届く全 repository が対象になるため、`doctor` が WARN を出します。
- 対象 repository は `--repo`、`GH_REPO`、または capsule 内 git repository の `origin` remote から client が推定し、broker に渡します。broker は空の作業 directory で `gh` を実行し、agent が書き換えられる git 設定を読みません。
- `--body-file FILE` は client（capsule 内）がファイルを読み、`--body-file -` に置き換えて stdin で送ります。broker 側でパスを開くことは一切ありません。そのため broker 側で読めるパスを制限する必要はありません（agent は capsule 内で読めるファイルなら `--body-file` を使わなくても本文に書けるため、client 側でのパス制限は防御になりません）。
- `pr create` で `--head` を省略すると、client が capsule 内の現在の branch を `--head` として付けます（broker は git checkout の外で `gh` を実行するため）。
- broker の返す出力とログからは、トークン文字列を `***` に置き換えます。実行・拒否したコマンドは `live/gh_broker.log` に記録されます（トークンは含みません）。`issue close --comment` の本文と `--title` はログに文字数だけを残します（`issue close` には `--body-file` が無く、本文が argv に載るため）。
- run が終わると broker は停止し、socket directory は削除されます。

制限と注意:

- 対話的な操作（prompt、`--web`、`--editor`）は使えません。issue / PR 番号は明示してください（現在の branch からの推定は broker 側ではできません）。`pr create --fill` のようにローカルの git を参照する使い方もできません。
- `git push` は broker の対象外です。capsule には GitHub の認証情報が無いため、HTTPS remote への push は失敗します（`gh auth setup-git` も token が無いので使えません）。push が必要な場合は、repo 限定の SSH deploy key を渡す（鍵ファイル自体は agent から読めます）か、host 側で push してください。
- agent は許可リストの範囲内でなら `gh` を自由に使えます（issue の大量作成など）。許可リストとトークンの権限（例: Issues: Read and write、Pull requests: Read and write、Metadata: Read、対象 repository のみ）の両方で絞ってください。
- capsule 内の `/usr/bin/gh` を直接呼ぶことはできますが、認証情報が無いため認証の必要な操作は失敗します。
- `gh` は image（`base-system.def`）に入っています。`gh` 追加前にビルドした `.sif` の場合は再ビルドしてください。`git pull` で `base-system.def` が更新されていれば `build-images.sh --run` で system image を作り直されます。確実に作り直す場合は `--run --force` を使います。
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

利用可能な agent CLI を表示します。対応する agent は `codex` と `claude` で、省略時は `claude`（Claude Code）を使います。

`--agent`、`--reviewers`、`--agents` はこの2種類だけを受け付けます。未対応の名前はエラーになります。wizard の保存済み agent が未対応なら `claude` に戻し、未対応の名前を含む保存済み reviewer / agents リストは空に戻します。

例:

```text
Available agents:
  codex        available /home/li/.local/bin/codex
  claude       available /home/li/.local/bin/claude
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
- image: `runtime/apptainer/base-system.sif`
- FUSE 前提条件: host の `/dev/fuse` と、image 内の `libfuse3` / `liblzo2`
- secrets file: 存在、permission（600 か）、設定済みの変数名、current directory 配下に無いか
- GitHub CLI broker: `secrets/gh.env` の `GH_TOKEN` と permission、`secrets/.env` に `GH_TOKEN` が書かれていないか
- `.agent-runs` の書き込み可否
- git repository / branch / dirty state

FUSE のチェックは常に WARN 止まりで、run を FAIL にはしません。capsule 内で nested `apptainer exec` を
使わないなら関係がないためです。使う場合は `--allow-fuse` と合わせて Troubleshooting を参照してください。

secrets と GitHub CLI broker のチェックも WARN 止まりです。どちらも任意のためです。

login node 上で `apptainer` や `uv` が見つからない場合は WARN です。compute node や image 内で提供される構成もあるため、WARN は即失敗とは限りません。

**`--all` を指定すると 2 agent 全ての auth を検証します。**使用しない agent の auth ファイルが未設定の場合、その agent の auth チェックが `[FAIL]` になります。使用する agent だけを確認する場合は `--agent NAME` を使ってください。

auth check の対象（store ファーストで確認、store になければ host fallback）:

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
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

## Conversation Archives

Conversation conversion runs on the host that launches `agentrun`, using system
Python's standard library. No model call, extra Python package, or image rebuild
is needed. The existing HOME cleanup locations are preserved:

- Interactive assist/resume: the launcher host finalizes the native session,
  exports its history, and then removes the temporary HOME after `srun` returns.
- `--submit`: the compute-node wrapper finalizes the native session and removes
  HOME. A detached collector on the submission host waits for Slurm completion,
  then exports the persisted history. Submitting a batch run remains asynchronous.

The collector polls `squeue` every five seconds. It uses `sacct` as a fallback if
`squeue` rejects an expired job ID. Queue query failures do not count as job
completion. The collector follows the original run ID if the wrapper appends a
human-readable title to the directory. A per-run lock prevents duplicate collectors.

```text
.agent-runs/<run>/live/history_export.json        export status, host, paths, warnings
.agent-runs/<run>/live/history_export.log         interactive export diagnostics
.agent-runs/<run>/live/session_finished.txt       batch wrapper cleanup marker
~/.agentrun/history/runs/<archive_id>/conversation.md  readable snapshot
~/.agentrun/history/runs/<archive_id>/metadata.json    run and native transcript metadata
~/.agentrun/history/index.sqlite3                     conversations table for all projects
~/.agentrun/history/jobs/<archive_id>.json             batch job ID, origin host, collector status
~/.agentrun/history/jobs/<archive_id>.log              batch collector diagnostics
```

All projects share the host user's `~/.agentrun/history/`. Override it with
`export AGENTRUN_HISTORY_DIR=/absolute/path/to/history` before launching
`agentrun`; use the same setting for manual exports and collector recovery.
Detached collectors inherit the resolved directory. The archive ID combines the
original run ID with a hash of the absolute `.agent-runs` parent path, so matching
run IDs in different projects do not overwrite each other. Exported Markdown is
stored only in the common directory; each run's status file provides its paths.
Existing project-local archives are left in place. Re-export their runs to add
them to the common index.

The manifest and archive metadata record `launcher_cwd`, the absolute host
directory where `agentrun` was invoked, separately from `repo`, the repository
selected with `--repo` and mounted at `/workspace`. Exporting later from another
directory does not change these values. Older manifests without `launcher_cwd`
export it as `null`; their original invocation directory cannot be recovered
reliably from the repository or the container's native transcript `cwd`.

The Markdown contains user messages and public assistant messages in transcript
order, with expandable tool inputs/results, command output, exit information
when recorded, and file changes. Codex command events retain combined output
when separate stdout/stderr fields are absent. Claude tool results support both
structured objects and error strings; tool-result records are not displayed as
user messages. Subagent transcripts and additional sessions created with `/new`
are included as separate sections. Native source/originator values, including
object-valued `source`, are retained in metadata.

System/developer instructions, reasoning/thinking records, opaque image payloads,
and duplicated API request blobs are excluded. Duplicate Codex message events
are not rendered twice. A torn final JSONL record is skipped with an archive note;
an invalid interior record fails the export rather than silently losing history.
The complete file is read, independently of the tail-only `resume --preview` helper.

Large Claude outputs under the persisted projects directory or run scratch can
be included from their companion text files. Claude's temporary directory is set
to `/scratch/claude` so background output remains accessible to the host. Paths
outside persisted storage are not opened. The archive records missing/non-text
companions and references to earlier paginated/forked history. It cannot restore
output already discarded by the CLI, or reconstruct missing ancestor history.
Native JSONL and persisted companion files remain in `.sessions/` and `scratch/`.

Each run creates one snapshot and one row in the SQLite `conversations` table.
Re-export updates that row. A resumed run gets a new snapshot linked through its
session key; earlier run snapshots remain unchanged. The Markdown and SQLite
paths survive the wrapper's run-directory rename and deletion of the project.
Re-export still requires the project's manifest and persisted native history.
Archive directories are private
and archive files are created with mode `0600`.

```bash
agentrun history                         # export the latest run now
agentrun history RUN_ID                  # export again, including renamed runs
agentrun history /absolute/path/to/run
agentrun history --watch RUN_ID          # wait/collect in the foreground on the submission host
```

The last command recovers a collector after the submission host or collector
process stops. Run it on the same host as the original submission. For a prepared
run submitted manually with `sbatch`, run it on the desired collection host once
`live/slurm_job_id.txt` is populated, or use plain `history` after completion.
The native session manifest is required; runs created before session persistence
was introduced cannot be exported by this command.

An export failure is recorded in `live/history_export.json` and the diagnostic
log. It does not change the agent's exit code or prevent the existing HOME cleanup.
The original persisted history remains available for a retry.

The SQLite index stores `archive_id` (primary key), `run_id`, `run_parent`, `agent`,
`repo`, `launcher_cwd`, `session_key`, `markdown_path`, `metadata_json`, `markdown`,
and `updated_at`. For example, search its text locally:

```python
import os
from pathlib import Path
import sqlite3

root = Path(os.environ.get("AGENTRUN_HISTORY_DIR", "~/.agentrun/history")).expanduser()
with sqlite3.connect(root / "index.sqlite3") as db:
    rows = db.execute(
        "SELECT archive_id, agent, repo, launcher_cwd, markdown_path "
        "FROM conversations WHERE markdown LIKE ?",
        ("%experiment%",),
    ).fetchall()
```

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
agentrun campaign --submit --agent codex --partition <partition> --goal path/to/goal.yaml --repo . "Run campaign"
agentrun review --submit --agent claude --partition <partition> --target-diff path/to/diff.patch --repo . "Review this diff"
agentrun multi-review --submit --agent codex --partition <partition> --agents claude,codex --repo . "Collect review notes"
```

重要:

- `--submit` なしでは prepare のみで、`sbatch` しません。
- `review` / `multi-review` は名前上 review 用ですが、現状は 1 agent だけを起動します。
- `--agents` は requested agents として prompt に入るだけです。
- 複数 agent を自動起動して比較・集約する機能は未実装です。

Every profile requires these common outputs (paths relative to `/runs`):

```text
live/status.json           live/heartbeat.txt
live/stdout.log            live/stderr.log
live/command_log.jsonl     live/events.jsonl
live/current_task.md
artifacts/report.md        artifacts/git_diff.patch
artifacts/metrics.json     artifacts/run_title.txt
```

`artifacts/report.md` and `artifacts/run_title.txt` must be non-empty. The title is
one lowercase line of about five words. The launcher-generated batch prompt,
profile definitions, shared rules, and `agentrun-contract` skill use this contract;
`verify-run` checks it along with the runtime metadata and job completion records.

Additional outputs by profile:

```text
assist        no additional outputs
experiment    artifacts/proposed_next.yaml
campaign      artifacts/proposed_next.yaml, artifacts/proposed_train.sbatch
review        reviews/review_findings.json
multi-review  reviews/{claude,codex}.md, reviews/summary.md,
              reviews/disagreements.json, reviews/final_recommendation.md
```

## Wizard Mode

`assist`/`experiment`/`campaign`/`review`/`multi-review` は `--partition`/`--gpus` を含めると10種類以上のフラグを組み立てる必要があり、手打ちが煩雑です。`agentrun wizard` は同じ起動ロジックへの、対話式（メニュー選択式）のフロントエンドです。

```bash
agentrun wizard
```

流れ:

1. TTY 必須（`[ -t 0 ] && [ -t 1 ]` を満たさない場合は対話せず即エラー終了）
2. UI backend を自動検出: **gum → whiptail/dialog → 標準 bash `read`/`select`** の順にフォールバックし、フォールバックする度に `"<tool> not found, falling back to <next>"` を1行 stderr に出力（インストール手順は表示しない）
3. mode → agent → launch style（assist なら「対話セッション（srun --pty）」か「バッチ投入（sbatch）」、それ以外のモードは「今すぐ sbatch するか」の confirm）→ repo → **partition** → **GPU数** → mem/cpus/time → bind mount → /dev/fuse → secrets / GitHub CLI broker（設定されている場合のみ）→ goal → task prompt → （review なら reviewers/target-diff/target-report、multi-review なら agents リスト）の順に質問
4. 最後に全項目のサマリと、同じ run を wizard なしで起動する **CLI コマンド**を表示し、"Launch this run?" で確認します。Yes ならその場で組み立てた引数で `assist`/`experiment`/`campaign`/`review`/`multi-review` と同じ起動処理（`write_plan`・auth staging・`srun --pty`/`sbatch`）を呼び出します。No なら何も実行せず、コマンドだけを表示して終了します。

### 入力と取り消し

- 入力欄には既定値が入った状態で表示され、そのまま編集できます（Enter で採用、消せば空欄）。plain（bash `read`）でも同様です。
- **Ctrl+C / Esc / Cancel ボタン / Ctrl+D で wizard 全体を中止**し、何も起動せずに終了します（exit 130）。whiptail は Ctrl+C のキー入力自体を受け付けないため、Esc か Cancel ボタンを使ってください。
- 値は入力した時点で検証し、不正ならエラーを表示して入力した値を残したまま再入力を促します。
  - repo: 存在する directory（`~` と相対パスは絶対パスに展開）。git repository でない場合は注意を表示
  - GPU数: 0 以上の整数。選んだ partition に sinfo 上 GPU が無い場合は注意を表示
  - memory: 数値 + 任意の `K`/`M`/`G`/`T`（例: `16000M`、`64G`）
  - CPU数: 1 以上の整数
  - walltime: Slurm の形式（`HH:MM:SS`、`MM`、`D-HH:MM:SS` など）
  - goal: 空欄、または存在するファイル
  - task prompt: batch 実行（interactive assist 以外）では必須
- bind mount は `--bind` と同じ `SRC:DST[:ro|rw]` 形式で 1 行に入力します。複数ある場合はスペースかカンマで区切ります（例: `~/data:/data:ro /scratch/me:/work`）。コマンドラインからコピーした `--bind`/`-B` はそのまま貼り付けても無視されます。`DST` を省略すると `SRC` と同じパスに mount します。存在しない `SRC`、絶対パスでない `DST`、`ro`/`rw` 以外のオプションはエラーになります。`none` で bind mount なしにします。1 行入力した後に "Add more?" で Yes を選ぶと、続きを別の行で追加できます（入力欄の長さ制限に掛かる場合や、分けて貼り付けたい場合）。gum の入力欄は文字数制限なしで起動します。

### partition の選択

`sinfo` が使える場合、partition は一覧から選びます。各 partition には sinfo が報告する GPU（例: `gpu (GPU: gpu:a100:4)`、`cpu (no GPU)`）が表示されます。一覧には `(cluster default: <name>)` と `Type a partition name...` も含まれ、後者を選ぶと名前を直接入力できます。sinfo に無い名前を入力した場合は、そのまま使うか確認します。`sinfo` が使えない環境では、従来どおり名前を入力します（空欄 = cluster default）。

### 前回の値の再利用

起動（Launch）した run の回答は `~/.agentrun/wizard-last` に保存され、次回の既定値になります。

- mode・agent・launch style・partition・GPU数・bind mount・/dev/fuse・secrets / broker の有無・multi-review の agents は、常に前回の値を既定値にします。
- memory・CPU数・walltime は、前回と同じ mode を選んだ場合だけ前回の値を使います（mode ごとに既定値が違うため）。
- repo・goal・task prompt・review の対象は、前回と同じ directory で wizard を起動した場合だけ使います（別の project で誤って前回の repo を使わないため）。
- `agentrun wizard --agent claude` のようにフラグを渡した項目は、前回の値より渡した値を優先します（質問はスキップされず、既定値として表示されます）。
- 中止した場合や、確認で No を選んだ場合は保存しません。

### 表示される CLI コマンド

サマリと起動直前に `Same run without the wizard:` として表示されるコマンドは、コピーしてそのまま同じ run を起動できます。profile の既定値と同じ memory/CPU/walltime、GPU 0、カレント directory の repo など、指定しなくても同じになる引数は省略します。

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
artifacts/run_title.txt         required, non-empty, single lowercase line of about five words
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
reviews/summary.md                review summary
reviews/disagreements.json        agent 間 disagreement 用。初期値は {}
reviews/final_recommendation.md   final recommendation
```

`home/` は container の `/home/sandbox` です。auth file や writable config はここに一時配置されます。`submit.sbatch` には cleanup trap が入っており、job 終了時に `<run_dir>/home/` は削除されます。

`scratch/` and `cache/` are separate directories for each run, mounted at `/scratch` and `/cache`. Their contents remain with that run directory until removed. They are not shared automatically with later runs, even on the same node.

初期作成直後や prepare-only run では、空ファイル、`{}`、`initialized` だけのファイルが多く残ります。これは異常ではありません。`--submit` した job が進むにつれて `live/` と `artifacts/` が更新されます。

### 認証ストアの仕組み

agent auth file は `$HOME/.agentrun/auth/<agent>/`（store）から `<run_dir>/home/` に staging され、container には `/home/sandbox` として渡されます。host `$HOME` の auth file を直接 read/write mount する構成ではありません。store にファイルがない場合のみ host `$HOME` に fallback します。

staging 対象の auth file:

```text
claude      $HOME/.agentrun/auth/claude/.claude/.credentials.json
            $HOME/.agentrun/auth/claude/.claude.json
codex       $HOME/.agentrun/auth/codex/.codex/auth.json
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

## Common Instructions

共通 instruction は以下を編集します。

```text
common/AGENTS.md
```

各 agent の instruction file は common file への symlink です。

```text
agents/claude/CLAUDE.md       -> ../../common/AGENTS.md
agents/codex/AGENTS.md        -> ../../common/AGENTS.md
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

URL 判定は `http(s)://`・`git@`・`ssh://`・`git://`・`*.git` のいずれかにマッチした場合で、この場合のみ `git clone --depth 1` を一時ディレクトリに対して行い、コピー完了後に即座に削除します（`common/skills/` にはクローン全体ではなく `skills/*` の中身だけが残ります）。取り込みに成功した skill が1件以上あれば、内部で `sync-claude` / `sync-codex` を自動実行します。取り込み後は `agentrun validate` で確認してください。

### デフォルト Skill の解説

`common/skills/` に含まれる skill とその役割を以下に示します。各 skill は `SKILL.md` として格納されており、フロントマター (`name:` / `description:`) によって agent がいつ参照すべきかを判断します。

| skill | 説明 |
| ----- | ---- |
| `uv` | Python プロジェクト・パッケージ・スクリプトの管理に使う `uv` コマンドのガイドです。`uv add`/`uv run`/`uvx` の使い分けや、venv の作成・管理方法を説明します。 |
| `agentrun-contract` | agentrun カプセル内で agent が書くべき出力ファイル・フォーマット・書き込みタイミングの一覧です。`live/status.json`・`artifacts/report.md` などの必須ファイルとモード別の追加要件、`verify-run` が何をチェックするかを記述します。 |
| `ruff` | Python ファイルを編集した後の lint・format 手順です。`post_edit_format.py` hook はフォーマッタを自動実行しないため、`uvx ruff check --fix` と `uvx ruff format` を手動実行する必要があることを説明します。 |
| `experiment-report` | `experiment`・`campaign`・`review`・`multi-review` 各モードで書くべきモード固有ファイルのスキーマです。`artifacts/proposed_next.yaml`・`artifacts/proposed_train.sbatch`・`reviews/review_findings.json`・`reviews/disagreements.json` などのフォーマットを記述します。 |
| `pytest` | `uv run pytest` を使ったテスト実行パターンと、テスト結果を `/runs/live/stdout.log` および `artifacts/metrics.json` に記録する方法を説明します。Project tests run through uv; system Python is reserved for capsule infrastructure. |
| `research-latex` | Creates Japanese and English research PDFs with academic, technical, and monograph templates, LuaLaTeX, Biber, structural validation, and page rendering for visual inspection. Bundled examples contain synthetic data. |
| `yomiyasu` | Refines Japanese prose while preserving meaning, with local lint and before/after review tools. Numeric values and research claims require separate verification. |

The default skill set contains seven skills: `uv`, `agentrun-contract`, `ruff`, `experiment-report`, `pytest`, `research-latex`, and `yomiyasu`.

`research-latex` is shared by Claude Code and Codex through the existing read-only skill mounts. Skill files become available in newly started runs without rebuilding the image. Its `siunitx` dependency requires an image built with `texlive-science`; rebuild older images before using the templates.

System Python remains installed for capsule hooks, agent startup metadata, and the GitHub broker. Research-latex uses `uv run --no-project python` with no additional Python packages; TeX Live and Poppler remain OS packages.

Inside a capsule, use `uv` to run the standard-library CLI and keep generated reports outside the read-only skill directory:

```bash
SKILL_ROOT=/home/sandbox/ai-agent-config/common/skills/research-latex
REPORT_DIR=/runs/artifacts/research-report
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" doctor
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" init --template technical --output "$REPORT_DIR"
# Replace synthetic examples with actual research content before delivery.
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" build --project "$REPORT_DIR"
uv run --no-project python "$SKILL_ROOT/scripts/research_latex.py" render --project "$REPORT_DIR" --all --dpi 150
```

Inspect every rendered page before delivering a report; structural validation does not check visual layout.


### Japanese prose editing with yomiyasu

`yomiyasu` is shared by Claude Code and Codex. It is bundled from
[nanaism/yomiyasu at commit 60bf877](https://github.com/nanaism/yomiyasu/tree/60bf877acebc86651e0b67d70112a66245f87758/skills/yomiyasu),
including its MIT license, Unicode license notice, reference documents, and local
checking scripts. The capsule-specific notes and command examples use uv; the
checking scripts are unchanged from that commit.

```bash
SKILL_ROOT=/home/sandbox/ai-agent-config/common/skills/yomiyasu
uv run --no-project python "$SKILL_ROOT/scripts/yomiyasu_lint.py" /runs/artifacts/report.md
uv run --no-project python "$SKILL_ROOT/scripts/yomiyasu_diff.py" /runs/before.md /runs/after.md --stance=説明
```

Use it when writing or revising Japanese prose. Preserve the requested report
format and structured output schemas. Lint findings are review candidates;
compare research numbers, units, formulas, citations, and claim strength with the
sources separately. For LaTeX documents, review the prose without changing TeX
commands or math, then compile and inspect the PDF with research-latex.

The tools use only the Python standard library. No additional OS/Python packages
or SIF rebuild are needed; the skill is available in newly started capsules.

## Hooks Maintenance

hook 実装は共通です。

```text
common/hooks/
```

ただし、どの hook をどの agent で使うかは agent ごとの manifest で管理します。

```text
agents/claude/hooks.manifest.json
agents/codex/hooks.manifest.json
```

既存 hook の中身だけを編集する場合:

```bash
agentrun validate
```

hook を追加・削除・リネームした場合:

```bash
agentrun sync-claude
agentrun sync-codex
agentrun validate
```

全ての `common/hooks/*.py` は、各 agent の manifest で active または ignored に分類されている必要があります。未分類 hook があると `validate` は失敗します。

全 agent の manifest は同一の event × matcher 形式を使います。

### デフォルト Hook の解説

`common/hooks/` に含まれる hook とその役割を以下に示します。

#### PreToolUse: コマンド実行フィルタ

これらは agent がコマンド実行ツール（Claude/Codex の `Bash`）を呼ぶ前に発火します。

| hook | 役割 |
| ---- | ---- |
| `block_dangerous_command.py` | `rm -rf /`・`rm -rf ~`、`mkfs`、`ssh`、`sudo` と、秘密ファイル（`.ssh/`、`id_rsa`/`id_ed25519`、`auth.json`、`.credentials.json`、`.env`/`.env.*`、`secrets/`、`.bashrc` など）へのアクセスをブロックします。判定はファイル名・パスだけで、`token`・`secret` といった単語（`AutoTokenizer`、`--max-new-tokens` など）では止めません。環境変数の値は対象外です。コマンド実行ツールとファイル系ツール（Read/Edit/Write/apply_patch など）の両方に適用されます。Codex の `apply_patch` は patch 本文ではなく、対象ファイルのパス（`*** Update File:` などの行）だけを判定します。 |
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

ファイル編集ツール（Claude の `Edit` / `Write`、Codex の `apply_patch`）が完了した後に発火します。

| hook | 役割 |
| ---- | ---- |
| `post_edit_format.py` | 編集イベントを `live/events.jsonl` に記録します。フォーマッタは自動実行しません。フォーマットが必要なプロジェクトでは agent 自身がコマンドとして実行するか、別 hook に追加してください。 |

#### Stop

agent セッションが終了するときに発火します。

| hook | 役割 |
| ---- | ---- |
| `stop_notify.py` | Slack Incoming Webhook で完了通知を送ります。スクリプト内の `SLACK_WEBHOOK_URL` に実際の URL を設定してください。未設定のままでも hook は失敗せず、通知をスキップします。agent 種別（Claude / Codex）を payload から自動検出します。 |
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

`auth login` は host CLI でのログイン（`claude auth login` / `codex login`）と store へのインポートを一括で実行します。

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

`base-system.def` を変更した場合は system image を再ビルドしてください。
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

Codex の実効 hook 経路は `/etc/codex/requirements.toml` です。Claude は `/home/sandbox/.claude/hooks/` を使います。

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
agentrun skill-install SOURCE_DIR|GIT_URL [SKILL_NAME...] [--force]
agentrun status
agentrun logs [--follow]
agentrun tail
agentrun list-runs
agentrun open-run [RUN_DIR]
agentrun verify-run [RUN_DIR|--run-id RUN_ID]
agentrun history [RUN_ID|RUN_DIR] [--watch]
```

主要 option:

```text
--agent NAME              codex, claude (default: claude)
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

### Wizard の戻る・パス補完・再開

wizard の各ステップで「← 戻る」または `:back` を使うと前の入力へ戻れます。`:cancel`、Esc、Ctrl+C はキャンセルです。bind のホスト側パスは Tab で補完できます。
CLI の Bash 補完は `install.sh --apply` で登録されます。現在のシェルでは `source runtime/agentrun/agentrun.bash` で有効にできます（`--bind` の source、`--repo`、`--goal`）。

```bash
agentrun resume --list
agentrun resume RUN_ID --preview
agentrun resume RUN_ID --time 02:00:00 --mem 16000M --cpus 4
agentrun resume  # 対話的に選択
```

wizard の mode でも `resume` を選べます。会話データは `.agent-runs/.sessions` に保存し、元のログを残して新しい run で再開します。保存前の旧 run は再開対象になりません。
起動時の installer ログは `live/agent_install.log`、インストールした CLI の情報は `artifacts/agent-cli.json` に保存します。compute node から公式 installer に接続できる必要があります。
