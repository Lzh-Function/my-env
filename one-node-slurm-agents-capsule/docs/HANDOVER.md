# 開発の引き継ぎ（WSL → 開発クラスタ）

2026-11-27 時点の引き継ぎです。これまで agentrun（このディレクトリ）と agent-history（`../agent-history`）は、研究室の WSL マシン（ホスト ID `mizuno-lab-wsl`）で開発してきました。これからは開発クラスタで、**agentrun で起動したセッションの中のエージェント**が開発を担当します（確保ジョブの中に常駐する想定）。つまり、開発担当は自分が開発しているツールの中で動きます。そのための注意を「[agentrun のセッションの中で開発するときの注意](#agentrun-のセッションの中で開発するときの注意)」にまとめました。引き継ぎ時点の最新コミットは `a9477fa` で、CI（GitHub Actions の「Slurm capsule tests」）は通っています。

## 目次

- [作業のルール](#作業のルール)
- [最初に確かめること](#最初に確かめること)
- [agentrun のセッションの中で開発するときの注意](#agentrun-のセッションの中で開発するときの注意)
- [テストの回し方](#テストの回し方)
- [Obsidian の Vault との取り決め](#obsidian-の-vault-との取り決め)
- [最近の大きな変更](#最近の大きな変更)
- [主なファイル](#主なファイル)

## 作業のルール

ユーザーと決めてきたルールです。

- **応答は日本語で書く。** 人が読む CLI とウィザードの表示も日本語にする。機械が読む形式（JSON、frontmatter のキー、ログの書式）は変えない。
- **コミットと push は、ユーザーの許可を得てから行う。**
- リポジトリ直下の `tmp/` はコミットしない。
- `~/workspace/infra/agent-capsule`（上流）は、指示がない限り触らない。参考にした修正の記録は [RUNTIME_BACKPORTS.md](RUNTIME_BACKPORTS.md) にある。
- 必要な処理は省略せずに最後まで行う。テストが通らないときに、偽の実装に切り替えたりテストを外したりして通さない。
- テストのために、実際のモデル呼び出しやエージェントの起動をしてよい。
- ユーザーの個人情報（氏名、メールアドレスなど）は外部のサービスに送らない。
- 機能を足したら、ウィザード（`wizard.sh` と `wizard_tools.sh`）からも使えるようにし、[USER_MANUAL.md](USER_MANUAL.md) と README を更新する。

## 最初に確かめること

確保ジョブ（`agentrun hold`）は Docker の疑似クラスタと CI でしか動かしていません。実際のクラスタで次の点を確かめてください。コンテナの中からは Slurm のコマンドを使えないので、ほとんどの項目はユーザーにログインノードで実行してもらい、結果を貼ってもらいます。

1. **ステップから GPU が見えるか（いちばん怪しい点）**：確保ジョブの中のセッションは `srun --jobid=<確保ジョブ> --overlap` のステップとして起動します。このとき `--gres` を指定していません（`agentrun` の `interactive_srun_args`、`hold.py` の `dispatch`）。Slurm の版や cgroup の設定（`ConstrainDevices`）によっては、ステップから GPU が見えないことがあります。
   - 開発担当のセッションが GPU のあるパーティションの確保ジョブで動いているなら、**自分のセッションで `nvidia-smi` を実行すれば、対話のステップについてはその場で確かめられます**（実行前に `cat /runs/capsule.yaml` で `hold_job:` を見て、確保ジョブの中にいることを確かめます）。
   - バッチ（`--submit`）のステップは、ユーザーに `agentrun assist --submit --repo <別の作業ツリー> "nvidia-smi の出力を report.md に書いて"` などで確かめてもらいます。
   - 見えなければ、ステップにも `--gres=gpu:<GPU数>` を渡すように直します（どちらも `--overlap` 付きなので、確保ジョブの GPU を共有したまま使えます）。
2. **確保する資源**：ユーザーに `agentrun hold status` と `scontrol show job <ジョブID>` を実行してもらい、パーティションのノードの CPU・メモリ・GPU がすべて取れているかを確かめます。確保ジョブは `--exclusive --mem=0 --cpus-per-task=<ノードのCPU数> --gres=gpu:<GPU数>` で投入します（`runtime/agentrun/hold.py` の `script()`）。パーティションの設定によっては、`--exclusive` や `--mem=0` が拒否されることがあります。
3. **時間の上限**：`--time` を省略すると、パーティションの上限（`sinfo %l`）を使います。上限が `infinite` のパーティションでは時間を指定しません。どちらの場合も、意図どおりに投入されるかを確かめます。
4. **確保ジョブのフォルダ**：既定では、`hold start` を実行したディレクトリの `.agent-runs/.hold/<日時>/` に作ります。計算ノードから見える場所でないと、ディスパッチャが動きません。

ほかに、実機での確認がまだ少ない機能があります。

- `/clear` のあとの会話を別ノートに分ける処理（`history_index.py`）。
- 3 つのエージェントによる相互監査（cross-review）。
- セッションログの返答の途中の行（`common/hooks/session_log.py`）。Claude Code は実際に起動して確かめました。Codex（PostToolUse の `additionalContext`）と Antigravity（PreInvocation の `injectSteps`）は、単体テストと CLI の仕様の確認だけです。`AGENTRUN_SESSION_LOG_INTERVAL=1`（1 分）で起動し、数分かかる作業を頼んで、`/runs/live/session_log.md` に「（途中）」の行が増えるかを確かめてください。開発担当が Codex か Antigravity なら、自分のセッションのログでも確かめられます。

## agentrun のセッションの中で開発するときの注意

### コンテナの中でできること・できないこと

- 開発担当はコンテナ（`apptainer exec --containall`）の中で動きます。見えるのは `/workspace`（`--repo` で指定した作業ツリー）と `/runs`（自分の run ディレクトリ）だけです。
- **コンテナの中では、Slurm のコマンド（`sbatch`、`srun`、`squeue`、`scontrol`）、Apptainer、Docker を使えません。** そのため、`agentrun` を実際に起動するテスト、確保ジョブの操作、`tests/slurm/docker/run.sh` は、自分では実行できません。
  - 疑似クラスタのテストは、push して CI に任せます。
  - 実機での確認は、ユーザーにログインノードで実行してもらいます。そのときは、実行してほしいコマンドを、そのまま貼り付けられる形で示してください。
- ユニットテストはコンテナの中で実行できます（Slurm のコマンドは偽物に差し替えてあります）。共通ルールのとおり、Python は `uv run --no-project python ...` で実行します。
- `git push` は GitHub の仲介（gh broker）を通して行えます。ただし、push はユーザーの許可を得てから行います。

### 自分が動いている agentrun を壊さない

- 開発担当のセッションの外側では、次のものがホスト側の agentrun のチェックアウトから動いています。
  - ログインノードの `agentrun`（bash）。srun の終了を待ち、そのあと会話履歴の保存などの後片付けをします。
  - 確保ジョブのディスパッチャ（`hold.py dispatch`）。
  - コンテナに読み取り専用でバインドされる hooks、skills、`CLAUDE.md` など。
- `install.sh --apply` は、`~/.local/bin/agentrun` に、そのチェックアウトへのシンボリックリンクを作ります。**開発は、普段使いのチェックアウトとは別の clone で行います**（ユーザーと決めた運用。たとえば普段使いが `~/my-env` なら、開発用は `~/my-env-dev`）。開発担当から見ると、その開発用の clone が `/workspace` です。`/workspace` の変更は、push してユーザーが普段使いのチェックアウトで `git pull` するまで、動いている agentrun には効きません。
  - 普段使いのチェックアウトを `--repo` にして開発してはいけません。開発中の変更がすぐに、動いている自分のセッションに効いてしまいます。bash はスクリプトを少しずつ読みながら実行するので、`agentrun` や `wizard.sh` を書き換えると、自分のセッションの終了処理や履歴の保存が壊れることがあります。
  - 開発用の clone は `main` のままで作業し、`main` に push します。
- 変更を普段使いの agentrun に入れるのは、push のあと、ユーザーがそのチェックアウトで `git pull` したときです。反映される時期は、変更したものによって違います。
  - `agentrun`（bash）と `wizard.sh` の変更は、次に起動したものから効きます。
  - hooks、skills、`common/AGENTS.md` の変更は、次に起動したセッションから効きます。
  - `hold.py` の変更は、確保ジョブを作り直すまで効きません（ディスパッチャは確保ジョブの中で動き続けるため）。キューの JSON の形式を変えるときは、古いディスパッチャが動いている場合のことも考えます。
  - 開発担当自身に変更を効かせるには、セッションを終えて `agentrun resume` し直してもらいます。
- 確保ジョブを解放する（`agentrun hold stop`）か、確保した時間が切れると、開発担当のセッションも終わります。作業の途中経過はこまめにコミットし、`/runs/live/current_task.md` を更新しておきます。終わったら、ユーザーに `agentrun resume` で再開してもらいます。
- 同じリポジトリでは、同時に 1 つのセッションしか動かせません（`.agentrun.lock`）。開発担当が使っている作業ツリーで、テスト用のセッションを起動することはできません。ユーザーにテストの起動を頼むときは、開発用の clone 以外のリポジトリか作業ツリーを `--repo` に指定してもらいます。
  - 変更を実機で試すには、ユーザーに開発用の clone の `runtime/agentrun/agentrun` を直接実行してもらいます。その場合、ほかのリポジトリを `--repo` に指定してもらいます。
  - ただし、`.sif` と `secrets/` は git で管理していないので、開発用の clone にはありません。普段使いのチェックアウトの `runtime/apptainer/base-system.sif` と `secrets/gh.env` を、シンボリックリンクで用意してもらいます。
- 確保ジョブの CPU・メモリ・GPU は、ほかのセッションと共有しています。重いテストを何本も並べて走らせないでください。

### 互換性

- **以前の版で作った run を resume できるようにしておく。** run ディレクトリの形式（`capsule.yaml`、`live/` の中のファイル、制御ファイル）を変えるときは、古い run を resume できること（後方互換）を確かめます。開発担当のセッション自身も、古い版で作られた run です。確保ジョブを追加したときは、変更前の版で作った run を resume できることを確かめました。
- 作業ログや一時ファイルは、リポジトリ直下の `tmp/` か `/runs` に置きます（`tmp/` はコミットしない）。

## テストの回し方

このディレクトリ（`install.sh` があるディレクトリ）で実行します。

```bash
uv run --no-project python -m unittest discover -s tests -p 'test_*.py'   # ユニットテスト（引き継ぎ時点で 342 件）。コンテナの中で実行できる
tests/slurm/docker/run.sh                                 # Docker の疑似クラスタ（Slurm + Apptainer）と、全ユニットテスト。Docker が必要
tests/slurm/docker/run.sh ClusterTests.test_hold_job_keeps_sessions_independent_and_runs_batch_inside   # 1 件だけ
```

- `mcp` パッケージがない Python では、MCP のテストは skip される。`jq` と `uv` がない場合も、一部のテストが skip される。
- 疑似クラスタには Docker が必要で、コンテナの中からは実行できない。push して CI に任せる。CI は `one-node-slurm-agents-capsule/**` を変更したときに動く。`gh run list -L 3` で結果を見る。CI のランナーは CPU が少ないので、CPU 数に依存するテストは、ランナーの CPU 数が少なくても通るように書く（`a9477fa` で直した）。
- 実際のクラスタで行う検査は `tests/slurm/` にある（ログインノードで実行するので、ユーザーに頼む）（[tests/slurm/README.md](../tests/slurm/README.md)）。
- ウィザードのテストは、質問の順番どおりに答えを並べる。質問を 1 つ足したら、`tests/test_wizard.py`、`tests/test_wizard_tools.py`、`tests/slurm/docker/test_cluster.py` の答えも足す。ウィザードの質問文は 1 行にする（テストが質問を行単位で見つけるため）。

## Obsidian の Vault との取り決め

`agentrun history export-md` と `agent-history export-md` が書き出すノートは、ユーザーの Obsidian の Vault に常駐するエージェントが読み取ります。ユーザーが両方のエージェントのやり取りを仲介しています。次のことを守ってください。

- frontmatter のキーを足したり名前を変えたりするときは、リリースの前にユーザー経由で Vault 側に知らせる。
- ノートを書き直すときも、`date`、`title`、`session_id`、`agent`、`project` の値と、ファイル名は変えない。
- ノートの形式を変えて FORMAT の番号を上げたら、push の知らせに新しい番号を書く（agent-history は現在 FORMAT=3）。
- `host` が決まらないときは、キーもタグも書かない（空の値や `unknown` は書かない）。ホスト ID は `david02`、`miyabi`、`home-wsl`、`mizuno-lab-wsl` の 4 つ。`david02` は agentrun のノートにだけ使う。
- 書き出し先は Vault の外に置く。Vault はフォルダの直下だけを読む（サブフォルダは読まない）ので、サブフォルダに分ける設定を足すなら既定はオフにする。
- agentrun のノートに `archive_host` を出すときは、先に Vault 側に知らせる。
- 書き出したノートは、内容で照合して更新する（agent-history は `session_id` と `agent`、agentrun は `archive_id`、`/clear` で分けたノートは加えて `conversation_id`）。Obsidian 側で名前を変えたり移動したりしたノートも、そのまま更新される。

## 最近の大きな変更

新しいものから順に並べます。詳しくは `git log` を見てください。

| コミット | 内容 |
| --- | --- |
| `9f51bc0`、`a9477fa` | **確保ジョブ**（`agentrun hold start/status/cancel/stop`）。`sbatch` でノード全体を確保し、対話のセッションは `--overlap` のステップとして、バッチは確保ジョブのキュー（`queue/*.json`）からステップとして起動する。確保ジョブがなければ今までどおり専用のジョブで動く（`--no-hold` を付けると、確保ジョブがあっても専用のジョブ）。ウィザードの「どこで起動しますか？」と、その他の機能の「確保ジョブ」から使える。[USER_MANUAL.md の確保ジョブの節](USER_MANUAL.md#hold) |
| `06760b5` | agent-history のノートに、どのマシンの会話かを示す `host` を書く（FORMAT=3）。 |
| `f113b41` | agentrun の履歴で、`/clear` のあとの会話を別の会話（`RUN~2` など）として一覧にし、別ノートに書き出す。サブエージェントの会話は元の会話に付け、相互監査の会話は時間が重なる会話に付ける。 |
| `9e73a6d` | 保存される形式の例（[history-examples/](history-examples/)）。 |
| `d4db278` | Obsidian で名前を変えたり移動したりしたノートも、内容で照合して更新する。 |

## 主なファイル

| ファイル | 役割 |
| --- | --- |
| `runtime/agentrun/agentrun` | 本体（bash）。引数の解釈、srun や sbatch での起動、各コマンドの入口 |
| `runtime/agentrun/hold.py` | 確保ジョブ（作成、選択、キュー、ディスパッチャ、状態の表示、停止） |
| `runtime/agentrun/overlap.py` | 実行中のジョブに重ねて起動する `--overlap` |
| `runtime/agentrun/active.py` | `agentrun ps` |
| `runtime/agentrun/history*.py`、`sessions.py`、`obsidian_note.py` | 会話履歴の回収、保存、一覧、書き出し |
| `runtime/agentrun/review*.py`、`agent-review` | 相互監査（設計は [CROSS_AGENT_REVIEW_DESIGN.md](CROSS_AGENT_REVIEW_DESIGN.md)） |
| `runtime/agentrun/wizard.sh`、`wizard_tools.sh` | ウィザード（起動までの流れと、その他の機能のメニュー） |
| `runtime/apptainer/` | コンテナイメージの定義とビルド |
| `common/`、`agents/`、`profiles/` | 全エージェント共通のルール、エージェントごとの設定、実行プロファイル |
| `tests/slurm/docker/` | Docker の疑似クラスタによる結合テスト |
