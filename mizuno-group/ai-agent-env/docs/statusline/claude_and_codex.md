Claude Code のステータスラインを3行構成にカスタマイズし、モデル名・コンテキスト使用率・レート制限使用状況を表示する設定を行った。

表示内容
[Claude Sonnet 4.6] ~/projects/myapp
CTX [██░░░░░░░░░░░░░░░░░░] 12%  $0.0023
Rate: 5h 34.5%  7d 18.2%

Line 1: モデル名 + カレントディレクトリ
Line 2: コンテキストウィンドウ使用率（プログレスバー）+ 累計コスト
Line 3: レート制限使用率（5時間・7日間）※ Claude.ai Pro/Max ユーザーのみ
前提条件
Claude Code がインストール済み
jq がインストール済み（Windows の場合は winget install jqlang.jq）
手順
1. スクリプトを作成する
~/.claude/statusline.sh を作成し、以下の内容を記述する。

#!/bin/bash
input=$(cat)

# Line 1: モデル + ディレクトリ
MODEL=$(echo "$input" | jq -r '.model.display_name // "Claude"')
CWD=$(echo "$input" | jq -r '.cwd // ""' | sed "s|$HOME|~|")
echo "[$MODEL] $CWD"

# Line 2: コンテキスト使用率 + コスト
CTX=$(echo "$input" | jq -r '.context_window.used_percentage // 0')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0' | awk '{printf "%.4f", $1}')
BAR_FILLED=$(echo "$CTX" | awk '{printf "%d", $1/5}')
BAR_EMPTY=$((20 - BAR_FILLED))
BAR=$(printf '%0.s█' $(seq 1 $BAR_FILLED 2>/dev/null))$(printf '%0.s░' $(seq 1 $BAR_EMPTY 2>/dev/null))
echo "CTX [${BAR}] ${CTX}%  \$${COST}"

# Line 3: レート制限（存在する場合のみ）
FIVE_H=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
WEEK=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
if [ -n "$FIVE_H" ] && [ -n "$WEEK" ]; then
  FIVE_H_FMT=$(printf "%.1f" "$FIVE_H")
  WEEK_FMT=$(printf "%.1f" "$WEEK")
  echo "Rate: 5h ${FIVE_H_FMT}%  7d ${WEEK_FMT}%"
fi

bashで実行権限を付与する。

chmod +x ~/.claude/statusline.sh

2. settings.json に設定を追加する
~/.claude/settings.json に statusLine セクションを追加する。

{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/statusline.sh",
    "padding": 1
  }
}

3. Claude Code を再起動する
設定は再起動後に反映される。アシスタントから最初のレスポンスを受け取ると、ステータスラインが更新される。

ポイント・注意事項
レート制限の表示条件
rate_limits フィールドは以下の条件を満たす場合のみ JSON に含まれる。

Claude.ai の Pro または Max プランのユーザー
セッション内で最初のアシスタントレスポンスを受け取った後
そのため、スクリプト内で // empty を使い、フィールドが存在しない場合は行を非表示にしている。

Windows 環境での注意
Claude Code on Windows は Git Bash 上で動作するため、bash スクリプトはそのまま使える。ただし jq は標準では含まれないため、別途インストールが必要。

winget install jqlang.jq

Codex CLIの場合
Codexの場合、Claude Codeのような作りこみはできず、config.tomlに表示したい内容を書くだけしかできない。が、残コンテキスト量や5h/7dの制限など表示できるので大きな問題はない。



[tui]
  status_line = [
    "model-with-reasoning",
    "project-root",
    "context-remaining",
    "git-branch",
    "five-hour-limit",
    "weekly-limit",
  ]

参考
Claude Code ステータスライン公式ドキュメント



