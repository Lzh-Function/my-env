#!/bin/bash

# Slack notification hook for Claude Code Stop event.
# Triggered when Claude finishes a turn; sends a brief summary of the last assistant message.

SLACK_WEBHOOK_URL="https://hooks.slack.com/services/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"

input=$(cat)

# Extract the last assistant message text from the transcript
summary=$(echo "$input" | jq -r '
  [.transcript[]? | select(.role == "assistant") | .content]
  | last
  | if type == "array" then
      [.[] | select(.type == "text") | .text] | join(" ")
    elif type == "string" then .
    else ""
    end
  | gsub("\n"; " ")
  | if length > 120 then .[0:120] + "..." else . end
' 2>/dev/null)

if [ -z "$summary" ] || [ "$summary" = "null" ]; then
  summary="作業が完了しました。"
fi

hostname=$(hostname -s 2>/dev/null || echo "unknown-host")

payload=$(jq -n \
  --arg summary "$summary" \
  --arg host "$hostname" \
  '{
    text: "*[\($host)] Claude Code 完了* :white_check_mark:\n\($summary)"
  }')

curl -s -o /dev/null \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$SLACK_WEBHOOK_URL" 2>/dev/null

# Clean up session-scoped temp files
rm -f /tmp/claude_allow_main_edit
rm -f /tmp/claude_python_env_*

exit 0
