# 会話履歴の例

agentrun が会話履歴をどんな Markdown で残すかの見本です。中身は作り話の短い会話で、実際の会話は入っていません。

| 会話 | 見どころ |
| --- | --- |
| Codex（`20261119_180000_assist_codex` と、それを resume した `20261120_100000_resume-assist_codex`） | 推論の要約（思考として残る）、コマンドの実行と出力、resume をまたいだ会話が 1 つのノートになる様子 |
| Claude Code（`20261120_110000_assist_claude`） | 思考、ツールの呼び出しと結果 |
| Antigravity（`20261120_120000_assist_antigravity`） | 思考、ファイルを読むツールとその結果 |

| フォルダ | 何の例か | 実際の場所 |
| --- | --- | --- |
| [`archive/`](archive/) | run が終わったときに保存する会話（`conversation.md`）と run の情報（`metadata.json`）。`history list`・`search` と書き出しの元になる | `~/.agentrun/history/runs/<run ID>-<run フォルダごとの番号>/`（`AGENTRUN_HISTORY_DIR` で変更可） |
| [`obsidian/`](obsidian/) | `agentrun history export-md DIR` が書き出すノート | `DIR` |

resume した run の保存は、それまでの会話を含んだ全体です。そのため `archive/` には resume 前と後の 2 つが並び、後のほうが長くなります。ノートは 1 つにまとまり（[学習率を下げた再学習](obsidian/2026-11-19%201800%20学習率を下げた再学習.md)）、プロパティの `runs` と `resumes` に resume の記録が残ります。

ノートでは、会話以外の部分（ツールの呼び出しと結果、思考、セッション情報など）を Obsidian の折りたたみにし、`%% agentrun:begin <種類> %%` 〜 `%% agentrun:end %%` の行で囲みます。ノートの時刻は日本時間、保存した会話の時刻は元の記録のまま（UTC）です。

例の中のパス（`/home/me/...`）、ホスト名（`login01`）、保存日時は、毎回同じ内容になるよう固定の値に置き換えています。

## 作り直す

形式を変えたときは、次で作り直します（一時フォルダに偽の run を作り、run の終了時と同じ保存と `history export-md` を実行して、結果をここに置きます）。

```bash
python3 docs/history-examples/make_examples.py
```

テスト（`tests/test_history.py`）は、ここにあるファイルが今の形式と同じかを確かめます。形式を変えて作り直し忘れると失敗します。
