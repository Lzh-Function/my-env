# Runtime fixes backported from agent-capsule

Reviewed the local `agent-capsule` history through `7778a21` on 2026-10-20 and
compared its runtime with `my-env` at `9d653ee`. Changes are adapted to the
existing `one-node-slurm-agents-capsule/` layout rather than merging the upstream tree.

| Source commit | Adopted fixes |
| --- | --- |
| `fa0d8e7` | Restore batch repository locking and quote smoke-test paths using the existing Slurm log directive helper. |
| `751baef` | Record selected reproducibility environment fields instead of credentials; prevent inherited implicit mounts and GitHub token injection; stop before agent startup if its enabled GitHub broker fails. |
| `eb91676` | Remove an obsolete `base-agent.sif` only after a successful forced system-image build. |
| `384dd38` | Explicitly request one node and one task for batch, interactive, and resumed runs, overriding inherited allocation counts. |
| `e626ed5` | Bind compute-node DNS files for agents and the existing GitHub broker; report installer DNS failures. |
| `1ef5a1b` | Bound installer, broker, terminal, finalizer, and process shutdown waits; keep the repository lock out of child processes; stop hung local `srun` after confirmed Slurm completion; cache shared history scans per listing. |
| `8979a86`, `0402ffa` | Download the Codex installer archive into its existing cache-backed temporary HOME instead of the container's small `/tmp`. The target did not contain conflict markers. |
| `dec534d` | Allocate distinct run directories atomically; normalize broker signal exit codes; fix zero-sized PTY fixtures in wizard tests. |
| `7778a21` | Keep Codex runtime helpers off NFS in container-local `/tmp`; retry transient HOME deletion failures and preserve diagnostics. |

The existing agent selection/default, profiles, native agent settings, hooks,
shared skills, host-side authentication/staging, auth store locations, and
single-image build architecture are retained. Codex and Claude Code remain the
only supported agents, with Claude Code as the default. The shared skills, Rust
and TeX image contents, centralized history directory/database, `launcher_cwd`
metadata, and host-only conversation export are retained. Added process helpers are internal
to the current launcher, with no new service or broker.

Excluded changes:

- Policy unification, managed native configuration, hook trust, and the new Slurm
  submission broker (`751baef`, `6ce1b14`, `37d2673`). Applying these would require
  changing the existing policy/configuration architecture. Native `--strict-config`
  flags that depend on that migration are not introduced by this backport.
- Authentication inside the container, shared user-state relocation, and config
  snapshot/direct-bind redesign (`e0fd1f2`, `384dd38`, `ad13c0a`, `2ed36e9`). Only
  the independently applicable one-node/one-task fix from `384dd38` is adopted.
  The target already binds its shared configs directly and has no `cp -a` snapshot.
- New partition support, notification services, Docker Slurm topology, and CI
  namespace setup. These are features or infrastructure changes, not runtime
  corrections needed for this port.
- Statusline executable-bit fix `e8d0191`: already present in the target.

Regression coverage uses synthetic installers, GitHub commands, Slurm queries,
PTYs, transient busy files, and generated batch scripts. Local tests do not
submit real jobs, download agent CLIs, or require an image rebuild.

For this launcher, interactive conversation export still runs on the launch host
before HOME deletion and has a 120-second cleanup deadline. Timeout failures are
recorded for manual retry with `agentrun history`. Batch HOME cleanup stays on the
compute node, including its completion marker; its detached history collector
stays on the submission host. Batch submission explicitly overrides inherited
node/task counts, and queue display filters cannot hide an active job from the
host collector. Existing archive/resume/default-agent tests remain in the suite.

## 2026-10-31の追加取り込み

`agent-capsule` の `origin/main`（`3cb663b`）と `upstream/main`（`0086011`）を
取得し、前回の基準 `7778a21` 以降を比較しました。`e5d0704` はこの版の
`69efbae` までを移植した更新でもあるため、同じ変更を重複して戻さず、追加の修正を選んでいます。

| 参照元 | 今回取り込んだ内容 |
| --- | --- |
| `3cb663b` | 相互監査のラウンド数・質問往復数・返信待ち期限・全体期限・累計実行時間の上限を撤廃。単発 CLI の時間制限は任意設定、既定 `0` は無制限 |
| `3cb663b` | 古い設定・状態・冪等要求の結果から制限を復活させない。Slurm の起動時の終了時刻を監査の固定期限として使わず、延長された割り当てに対応 |
| `e5d0704` | コンテナで保存済みの監査モデル・effort・任意の単発 CLI 時間制限を読み、`--cleanenv` 後も維持 |
| `e5d0704` | 監査側で更新された認証情報だけを、元のバイト列のまま既存の run-HOME 同期経路へ返す。未変更の認証で別の更新を上書きしない |
| `e5d0704` | ホストの Slurm 照会を専用 process group と一時ファイルで管理し、子孫が保持する PIPE による待機を防ぐ。SUSPENDED を稼働中、保持された終了済みレコードを完了と判定 |
| `e5d0704` | バッチの改名をロック解放・完了マーカーより前に実施し、準備済みの別 run を指す latest を維持。改名にも有限の待ち時間を設ける |
| `e5d0704` | resume の一覧は会話ごとに最新 run のみ表示し、過去の run ID による直接選択は維持 |
| `e5d0704` | 計算ノード側で対話 CLI の停止を検出して続行し、Ctrl+Z 後の操作不能を防ぐ。Ctrl+C・終了コード・端末設定の復元を維持 |

この版の2エージェント構成、単一 SIF、ホスト側認証、既定の履歴自動保存、
`/node-scratch`、Git push broker、既存の hook と設定方式は維持します。
対話履歴の書き出しは引き続き HOME 削除前に投入元で実施し、書き出し中は repo ロックを保持しません。
レビューの回数・時間制限の撤廃は、入力サイズ制限や安全な停止処理の待ち時間には適用しません。

参照元の管理 policy・Slurm broker・Antigravity・通知・認証基盤・任意機能への切り替えは
構成が異なるため取り込みません。`3cb663b` の CI 依存追加に相当する uv / MCP SDK は、
この版の Docker 回帰環境ですでに導入済みです。共通 skill と日本語マニュアル・設計書は新しい動作に揃えています。

この追加取り込みによる SIF の再ビルドは不要です。更新後の新規起動または resume で反映されます。

検証では、ホストの回帰テスト217件と、実際のSlurm / Apptainerを使う結合テスト20件が成功しました。
レビュー状態機械では22ラウンド・7往復・期限切れの旧状態を確認し、結合テストでは
両workerとCLI / MCPの4条件で、第2ラウンド承認後の編集を第3ラウンドで再確認しました。
エージェントの返答・認証・配布内容は固定fixtureで、外部モデルAPIや実アカウントは使っていません。

コンテナ内の回帰テストも217件すべて成功し、ホスト・コンテナともスキップはありません。
共通skillの検証、変更した主要Python処理と新規端末ガードの静的検査、shell構文、差分の空白も確認しました。
