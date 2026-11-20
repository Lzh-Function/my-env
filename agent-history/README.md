# agent-history

ローカルで使う Claude Code・Codex・Antigravity（`agy`）の会話を、まとめて保存・検索し、Obsidian 向けのノートに書き出すコマンドです。agentrun の `history` と同じ機能を、`$HOME` の下にある普段の会話に対して使えます。agentrun とは関係なく単独で動きます。

## できること

- **保存**: 3 つの CLI の会話を `~/agent-history/` に Markdown として保存し、検索用のデータベース（SQLite）に登録します。変わった会話だけを保存し直します。
- **一覧と検索**: 最後に動いた順の一覧、全文検索、CLI・作業ディレクトリでの絞り込み。
- **Obsidian への書き出し**: 1 会話 1 ノート。ツールの呼び出しと結果、コマンド出力は折りたたみ表示にし、印の行で囲みます（会話だけを読みたいときに機械的に除けます）。
- **名前の変更**: 会話に自分で名前を付けられます。
- **自動保存**: Stop フックを各 CLI の設定に登録すると、エージェントが返答を終えるたびにその会話を保存し直します。

## インストール

[uv](https://docs.astral.sh/uv/) を使います。Python 3.11 以上で、ほかの依存はありません。

```bash
./install.sh                 # agent-history コマンドを入れる（このディレクトリの変更がそのまま反映される）
agent-history sync           # 今ある会話を保存
agent-history hooks install  # 返答ごとの自動保存を登録
```

外すときは `agent-history hooks uninstall` のあとで `./install.sh --remove` を実行します。

## 使い方

```bash
agent-history list                              # 最近の会話（最後に動いた順）
agent-history list --agent codex --project paper  # Codex の、作業ディレクトリに paper を含む会話
agent-history search OOM 学習率                   # すべての語を含む会話（前後の文も表示）
agent-history export-md ~/vault/agents          # Obsidian 向けに書き出す
agent-history rename 886e462d 論文の図の修正       # 名前を付ける（ID は list の「ID:」、先頭だけでも可）
agent-history rename 886e462d --clear           # 付けた名前を消し、CLI が付けた名前に戻す
agent-history sync --force                      # 変わっていない会話も作り直す
```

`list`・`search`・`export-md` は、実行の前に変わった会話を保存し直します。保存済みの内容だけで済ませるときは `--no-sync` を付けます。

一覧には、何も依頼せずに閉じた会話（`/exit` だけなど）は出しません。書き出しでも除き、以前に書き出したノートがあれば消します。

## 対象にする会話

| CLI | 読む場所 | 会話の名前 |
| --- | --- | --- |
| Claude Code | `~/.claude/projects/*/<会話ID>.jsonl`（サブエージェントは `<会話ID>/subagents/` から同じノートに入れる） | `/rename` で付けた名前、なければ Claude Code が付けた最新の名前 |
| Codex | `~/.codex/sessions/`（と `archived_sessions/`）の `rollout-*.jsonl` | `~/.codex/session_index.jsonl` の最新の名前 |
| Antigravity | `~/.gemini/antigravity-cli/brain/<会話ID>/.system_generated/logs/` の記録 | `cache/conversation_metadata.json` の名前 |

`CLAUDE_CONFIG_DIR`・`CODEX_HOME` を設定していれば、その場所を読みます。サブエージェントだけの会話（Codex・Antigravity）は、別の会話としては扱いません。

モデルの思考（thinking）は、元の記録に読める形で残っているものを保存します。Claude Code は `thinking` ブロック、Antigravity は `thinking` の項目、Codex は推論の要約（`summary`）です。Codex は推論そのものを暗号化して保存するため、要約がない場合は残りません。システム指示と Codex のアカウント情報は保存しません。Claude Code の長い出力が別ファイルにある場合は、Claude Code 自身の保存場所（`~/.claude` と一時フォルダ）にあるものだけを取り込みます。

## 保存先

```text
~/agent-history/
  archives/<CLI>/<会話ID>.md   会話ごとの Markdown
  index.sqlite3                一覧・検索用のデータベース
  titles.json                  rename で付けた名前
  hook.log                     自動保存の記録（大きくなったら古い半分を捨てる）
  cache/<CLI>-<会話ID>/         続きから読むための記録（どこまで読んだか、変換済みの本文）
```

長い会話でも、2 回目からは前回の続き（追記された分）だけを読みます。どこまで読んだかと変換済みの本文を `cache/` に置くため、`archives/` とほぼ同じだけの容量を使います。CLI が記録ファイルを書き直した場合（Antigravity の要約時など）は、その会話だけ最初から読み直します。`cache/` を消しても、次の保存で作り直されるだけです。

`AGENT_HISTORY_DIR` で場所を変えられます。ファイルは自分だけが読める権限で作ります。

書き出し先のフォルダには、管理用の `.agent-history-export.json` を置きます。どの会話をどのノートに書いたかの記録で、2 回目以降は変わった会話だけを書き直し、自分で作ったノートには触れません。消すと、次の書き出しで全部を ` (2)` 付きの名前で書き直すことになるので、残しておいてください。

## 書き出すノート

- ファイル名は `2026-11-20 1000 図の修正.md` のように、会話を始めた日時と名前です。時刻は日本時間（`AGENT_HISTORY_TIMEZONE` で変更可）です。
- 冒頭のプロパティは `date`・`last_active`・`agent`・`project`（作業ディレクトリ）・`title`・`session_id`・`archived_at`・`tags: [agent-history]` です。
- 会話以外の部分（ツールの呼び出しと結果、コマンド出力、モデルの思考、セッション情報、自動で挿入されたメッセージ）は、折りたたみ表示にし、行頭の `%% agent-history:begin <種類> %%` の行から `%% agent-history:end %%` の行までに入れます。種類は `tool`・`thinking`・`session`・`injected` です。会話だけを読むときは次で除けます。

```bash
sed '/^%% agent-history:begin /,/^%% agent-history:end %%$/d' NOTE.md
```

## 自動保存（Stop フック）

`agent-history hooks install` は、各 CLI のフック設定に Stop フックを 1 つ足します。ほかのツールのフックはそのまま残し、書き換える前のファイルを `<ファイル名>.agent-history.bak` に残します。

| CLI | 登録先 |
| --- | --- |
| Claude Code | `~/.claude/settings.json` の `hooks.Stop` |
| Codex | `~/.codex/hooks.json` の `hooks.Stop` |
| Antigravity | `~/.gemini/config/hooks.json` の `agent-history` |

エージェントが返答を終えるたびに、その会話だけを保存し直します。フックはすぐに返事をして、保存は裏で行うので、エージェントを待たせません。保存するだけで、ノートは書き出しません（`export-md` を実行したときにまとめて書きます）。結果は `~/agent-history/hook.log` に残ります。

- **Codex**：Codex は、新しく足されたフックを信頼してよいか、次の起動時に確認します。承認すると動き始めます。
- **登録の確認と解除**：`agent-history hooks status` で登録の有無を確かめられ、`agent-history hooks uninstall` で外せます（`--agent` で CLI を絞れます）。
- **登録し直しが要るとき**：フックの設定には、このディレクトリと Python の場所を書き込みます。ディレクトリを移した場合は `hooks install` をもう一度実行してください。

## テスト

```bash
python3 -m unittest discover -s tests
```

偽の `$HOME` に 3 つの CLI の形式の会話を置き、保存・一覧・検索・書き出し・名前の変更・フックの登録と解除・Stop フックからの保存を確かめます。モデルは呼びません。
