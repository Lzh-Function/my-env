#!/bin/bash

# Slack notification for Claude Code PermissionRequest events.
# Receives tool name and full tool input, so we can show what exactly needs permission.

SLACK_WEBHOOK_URL="https://hooks.slack.com/services/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"

input=$(cat)
hostname=$(hostname -s 2>/dev/null || echo "unknown-host")

tool_name=$(echo "$input" | jq -r '.tool_name // "unknown"' 2>/dev/null)

# Format detail line based on tool type
detail=$(echo "$input" | jq -r '
  if .tool_name == "Bash" then
    "```" + (.tool_input.command // "?") + "```"
  elif (.tool_name == "Write" or .tool_name == "Edit" or .tool_name == "Read") then
    "`" + (.tool_input.file_path // "?") + "`"
  elif .tool_name == "WebFetch" then
    "`" + (.tool_input.url // "?") + "`"
  elif .tool_name == "WebSearch" then
    "`" + (.tool_input.query // "?") + "`"
  else
    ((.tool_input // {}) | to_entries | map("\(.key): `\(.value)`") | join("\n"))
  end
' 2>/dev/null)

payload=$(jq -n \
  --arg host "$hostname" \
  --arg tool "$tool_name" \
  --arg detail "$detail" \
  '{
    text: "*[\($host)] :bell: Permission Request — \($tool)*\n\($detail)"
  }')

curl -s -o /dev/null \
  -X POST \
  -H "Content-Type: application/json" \
  -d "$payload" \
  "$SLACK_WEBHOOK_URL" 2>/dev/null

exit 0
