#!/usr/bin/env bash
input=$(cat)

# Line 1: model + CWD
MODEL=$(printf '%s' "$input" | jq -r '.model.display_name // "Gemini"')
CWD=$(printf '%s' "$input" | jq -r '.cwd // ""' | sed "s|$HOME|~|")
printf '[%s] %s\n' "$MODEL" "$CWD"

# Line 2: context usage (no billing cost in agy — show remaining% instead)
CTX=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // 0')
REM=$(printf '%s' "$input" | jq -r '.context_window.remaining_percentage // 0' | awk '{printf "%.1f", $1}')
BAR_FILLED=$(printf '%s' "$CTX" | awk '{n=int($1/5); if(n>20) n=20; print n}')
BAR_EMPTY=$((20 - BAR_FILLED))
BAR=$(printf '%0.s█' $(seq 1 "$BAR_FILLED" 2>/dev/null))$(printf '%0.s░' $(seq 1 "$BAR_EMPTY" 2>/dev/null))
printf 'CTX [%s] %s%%  Rem: %s%%\n' "$BAR" "$CTX" "$REM"

# Line 3: agent state + git branch
STATE=$(printf '%s' "$input" | jq -r '.agent_state // "idle"')
BRANCH=$(printf '%s' "$input" | jq -r '.vcs.branch // ""')
DIRTY=$(printf '%s' "$input" | jq -r '.vcs.dirty // false')
if [ -n "$BRANCH" ]; then
    [ "$DIRTY" = "true" ] && BRANCH_FMT="${BRANCH}*" || BRANCH_FMT="$BRANCH"
    printf 'State: %s  Branch: %s\n' "$STATE" "$BRANCH_FMT"
else
    printf 'State: %s\n' "$STATE"
fi
