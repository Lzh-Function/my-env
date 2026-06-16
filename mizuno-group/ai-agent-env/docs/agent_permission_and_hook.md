# 計算ノード下のエージェントに許可しないこと
- `git push`：最終的なpushはユーザーが実行する。commitまでしか許可しない。
- `.git`ファイルの読み書き：直接.gitを読みに行くことは禁止する。gitコマンドを利用せよ。
- `.env`・`.bashrc`・`.workspace_rc`ファイルの読み書き・`.secret`・`.ssh`ディレクトリ下の読み書き：機密情報
- `pip`の直接利用：uv環境でpythonを運用するため、絶対にpipを直接用いてはならない。`uv pip list`などは許可するが、`uv pip install ...`も許可しない。
- `ssh ...`・`sudo ...`・`rm -rf /*`の利用：当たり前。

**これらは全て可能ならsettingsファイルに加えてPreUseTool時のhookで強く抑止したい。**

# 追加で欲しいhook
- stop時slackへの通知：現在claude専用となっているが、全エージェント対応とする。ノード名とエージェント名の表示（環境変数などで取得？）とともに、現在一切機能していない作業summaryも含める。