#!/usr/bin/env bash
input=$(cat)

# Line 1: model + CWD
MODEL=$(printf '%s' "$input" | jq -r '.model.display_name // "Claude"')
CWD=$(printf '%s' "$input" | jq -r '.cwd // ""' | sed "s|$HOME|~|")
printf '[%s] %s\n' "$MODEL" "$CWD"

# Line 2: context usage + cost
CTX=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
COST=$(printf '%s' "$input" | jq -r '.cost.total_cost_usd // 0' | awk '{printf "%.4f", $1}')
BAR_FILLED=$(printf '%s' "$CTX" | awk '{n=int($1/5); if(n>20) n=20; print n}')
BAR_EMPTY=$((20 - BAR_FILLED))
BAR=$(printf '%0.s█' $(seq 1 "$BAR_FILLED" 2>/dev/null))$(printf '%0.s░' $(seq 1 "$BAR_EMPTY" 2>/dev/null))
printf 'CTX [%s] %s%%  $%s\n' "$BAR" "$CTX" "$COST"

# Line 3: rate limits (Pro/Max only — field absent otherwise)
FIVE_H=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')
WEEK=$(printf '%s' "$input" | jq -r '.rate_limits.seven_day.used_percentage // empty')
if [ -n "$FIVE_H" ] && [ -n "$WEEK" ]; then
    FIVE_H_FMT=$(printf '%.1f' "$FIVE_H")
    WEEK_FMT=$(printf '%.1f' "$WEEK")
    printf 'Rate: 5h %s%%  7d %s%%\n' "$FIVE_H_FMT" "$WEEK_FMT"
fi
