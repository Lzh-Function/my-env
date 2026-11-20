#!/usr/bin/env bash
# Antigravity CLI status line: the same three lines as agents/claude/statusline.sh.
input=$(cat)

# Line 1: model + CWD
MODEL=$(printf '%s' "$input" | jq -r '.model.display_name // "Antigravity"')
CWD=$(printf '%s' "$input" | jq -r '.cwd // ""' | sed "s|$HOME|~|")
printf '[%s] %s\n' "$MODEL" "$CWD"

# Line 2: context usage + cost
CTX=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0' | awk '{printf "%.0f", $1}')
COST=$(printf '%s' "$input" | jq -r '.cost.total_usd // 0' | awk '{printf "%.4f", $1}')
BAR_FILLED=$(printf '%s' "$CTX" | awk '{n=int($1/5); if(n>20) n=20; print n}')
BAR_EMPTY=$((20 - BAR_FILLED))
# printf repeats its format once even with no arguments, so an empty part stays empty.
BAR=""
[ "$BAR_FILLED" -eq 0 ] || BAR=$(printf '%0.s█' $(seq 1 "$BAR_FILLED"))
[ "$BAR_EMPTY" -eq 0 ] || BAR="$BAR$(printf '%0.s░' $(seq 1 "$BAR_EMPTY"))"
printf 'CTX [%s] %s%%  $%s\n' "$BAR" "$CTX" "$COST"

# Line 3: quota left per bucket (absent until the CLI reports it)
QUOTA=$(printf '%s' "$input" | jq -r '(.quota // {}) | to_entries | map(select(.value.remaining_fraction != null) | "\(.key) \((1 - .value.remaining_fraction) * 100 | floor)%") | join("  ")')
if [ -n "$QUOTA" ]; then
    printf 'Quota used: %s\n' "$QUOTA"
fi
