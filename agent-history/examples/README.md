# 保存される形の例

agent-history がどんな Markdown を作るかの見本です。中身は作り話の短い会話（Claude Code・Codex・Antigravity で 1 つずつ）で、実際の会話は入っていません。

| フォルダ | 何の例か | 実際の場所 |
| --- | --- | --- |
| [`archive/`](archive/) | 保存した会話（`sync` と自動保存が作るもの）。検索と書き出しの元になる | `~/agent-history/archives/<CLI>/<会話ID>.md` |
| [`obsidian/`](obsidian/) | Obsidian 向けに書き出したノート（`export-md` が作るもの） | `export-md` に渡したフォルダ |

それぞれの見どころ:

- **Claude Code**（[保存](archive/claude.md) / [ノート](obsidian/2026-11-20%201000%20図の凡例の修正.md)）: 思考、ツールの呼び出しと結果、2 回目の依頼、サブエージェントの会話（ノートの最後の「サブエージェントのセッション」）。
- **Codex**（[保存](archive/codex.md) / [ノート](obsidian/2026-11-20%201100%20テストの確認.md)）: 推論の要約（思考として残る）、コマンドの実行と出力。
- **Antigravity**（[保存](archive/antigravity.md) / [ノート](obsidian/2026-11-20%201200%20README%20の手順追加.md)）: 思考、ファイルを読むツールとその結果。

保存した会話は、ツールの呼び出しや思考を `<details>` で畳んだ普通の Markdown です。ノートはこれを Obsidian の折りたたみ（callout）に変え、会話以外の部分を `%% agent-history:begin <種類> %%` 〜 `%% agent-history:end %%` の行で囲んだものです。ノートの時刻は日本時間、保存した会話の時刻は元の記録のまま（UTC）です。

## 作り直す

形式を変えたときは、次で作り直します（一時フォルダに偽の `$HOME` を作って `sync` と `export-md` を実行し、結果をここに置きます）。

```bash
python3 examples/make_examples.py
```

テスト（`tests/test_agent_history.py`）は、ここにあるファイルが今の形式と同じかを確かめます。形式を変えて作り直し忘れると失敗します。
