import re
from pathlib import Path

path = Path("runtime/agentrun/agentrun")
content = path.read_text()

# Insert after validate_claude_sync

antigravity_code = """
antigravity_hooks_manifest() {
    printf '%s\\n' "$ROOT_DIR/agents/antigravity/hooks.manifest.json"
}

render_antigravity_hooks_json() {
    local output="$1"
    jq '
      .hooks |
      group_by(.event) |
      map({
        key: .[0].event,
        value: [
          .[] | {
            matcher: .matcher,
            hooks: [
              .entries[] |
              {"type": "command", "command": ("~/.gemini/antigravity-cli/hooks/" + .script)} +
              if .if then {"if": .if} else {} end
            ]
          }
        ]
      }) |
      from_entries
    ' "$(antigravity_hooks_manifest)" > "$output"
}

validate_antigravity_hook_manifest() {
    local manifest hook failed=0
    manifest="$(antigravity_hooks_manifest)"
    if [ ! -f "$manifest" ]; then
        printf '[FAIL] agents/antigravity/hooks.manifest.json\\n'
        return 1
    fi
    if ! jq -e '
      type == "object" and
      (.hooks | type == "array" and all(.[]; (
        .event | type == "string"
      ) and (
        .matcher | type == "string"
      ) and (
        .entries | type == "array" and all(.[]; (.script | type == "string"))
      ))) and
      ((.ignored // []) | type == "array" and all(.[]; type == "string"))
    ' "$manifest" >/dev/null; then
        printf '[FAIL] antigravity-hooks-manifest:shape\\n'
        return 1
    fi
    while IFS= read -r hook; do
        [ -n "$hook" ] || continue
        case "$hook" in
            ""|*/*|*..*|*[!A-Za-z0-9_.-]*)
                printf '[FAIL] antigravity-hooks-manifest:invalid-name:%s\\n' "$hook"
                failed=1
                continue
                ;;
        esac
        if [ -x "$ROOT_DIR/common/hooks/$hook" ]; then
            printf '[OK] antigravity-hooks-manifest:%s\\n' "$hook"
        else
            printf '[FAIL] antigravity-hooks-manifest:%s\\n' "$hook"
            failed=1
        fi
    done < <(jq -r '[.hooks[].entries[].script] | unique[]' "$manifest")
    while IFS= read -r hook; do
        [ -n "$hook" ] || continue
        case "$hook" in
            ""|*/*|*..*|*[!A-Za-z0-9_.-]*)
                printf '[FAIL] antigravity-hooks-manifest:invalid-ignored-name:%s\\n' "$hook"
                failed=1
                continue
                ;;
        esac
        if [ -e "$ROOT_DIR/common/hooks/$hook" ]; then
            printf '[OK] antigravity-hooks-ignored:%s\\n' "$hook"
        else
            printf '[FAIL] antigravity-hooks-ignored:%s\\n' "$hook"
            failed=1
        fi
    done < <(jq -r '(.ignored // [])[]' "$manifest")
    local covered unclassified=0
    covered="$(jq -r '[.hooks[].entries[].script, (.ignored // [])[]] | unique[]' "$manifest")"
    for hook_path in "$ROOT_DIR"/common/hooks/*.py; do
        [ -e "$hook_path" ] || continue
        hook="$(basename "$hook_path")"
        if printf '%s\\n' "$covered" | grep -Fxq "$hook"; then
            :
        else
            printf '[FAIL] antigravity-hooks-unclassified:%s - add it to hooks or ignored\\n' "$hook"
            unclassified=1
            failed=1
        fi
    done
    if [ "$unclassified" -eq 0 ]; then
        printf '[OK] antigravity-hooks-classified:all-common-hooks\\n'
    fi
    return "$failed"
}

command_sync_antigravity() {
    if [ "$#" -ne 0 ]; then
        printf 'sync-antigravity takes no arguments\\n' >&2
        return 2
    fi
    if ! command -v jq >/dev/null 2>&1; then
        printf 'jq is required for sync-antigravity\\n' >&2
        return 1
    fi
    validate_antigravity_hook_manifest >/dev/null
    local tmp
    tmp="$(mktemp)"
    render_antigravity_hooks_json "$tmp"
    mv "$tmp" "$ROOT_DIR/agents/antigravity/hooks.json"
    chmod 0644 "$ROOT_DIR/agents/antigravity/hooks.json"
    ln -sfnT ../../common/AGENTS.md "$ROOT_DIR/agents/antigravity/AGENTS.md"
    ln -sfnT ../../common/AGENTS.md "$ROOT_DIR/agents/antigravity/GEMINI.md"
    ln -sfnT ../../common/skills "$ROOT_DIR/agents/antigravity/skills"
    printf '[OK] synced agents/antigravity/hooks.json from agents/antigravity/hooks.manifest.json\\n'
    printf '[OK] synced agents/antigravity/AGENTS.md -> ../../common/AGENTS.md\\n'
    printf '[OK] synced agents/antigravity/GEMINI.md -> ../../common/AGENTS.md\\n'
    printf '[OK] synced agents/antigravity/skills -> ../../common/skills\\n'
}

validate_antigravity_sync() {
    local failed=0 tmp
    if validate_antigravity_hook_manifest; then
        printf '[OK] antigravity-hooks-manifest\\n'
    else
        failed=1
    fi
    tmp="$(mktemp)"
    render_antigravity_hooks_json "$tmp"
    if cmp -s "$tmp" "$ROOT_DIR/agents/antigravity/hooks.json"; then
        printf '[OK] antigravity-hooks-generated:agents/antigravity/hooks.json\\n'
    else
        printf '[FAIL] antigravity-hooks-generated:agents/antigravity/hooks.json - run agentrun sync-antigravity\\n'
        failed=1
    fi
    rm -f "$tmp"
    if [ "$(readlink "$ROOT_DIR/agents/antigravity/AGENTS.md" 2>/dev/null || true)" = "../../common/AGENTS.md" ]; then
        printf '[OK] antigravity-agents-link:agents/antigravity/AGENTS.md\\n'
    else
        printf '[FAIL] antigravity-agents-link:agents/antigravity/AGENTS.md - run agentrun sync-antigravity\\n'
        failed=1
    fi
    if [ "$(readlink "$ROOT_DIR/agents/antigravity/GEMINI.md" 2>/dev/null || true)" = "../../common/AGENTS.md" ]; then
        printf '[OK] antigravity-agents-link:agents/antigravity/GEMINI.md\\n'
    else
        printf '[FAIL] antigravity-agents-link:agents/antigravity/GEMINI.md - run agentrun sync-antigravity\\n'
        failed=1
    fi
    if [ "$(readlink "$ROOT_DIR/agents/antigravity/skills" 2>/dev/null || true)" = "../../common/skills" ]; then
        printf '[OK] antigravity-skills-link:agents/antigravity/skills\\n'
    else
        printf '[FAIL] antigravity-skills-link:agents/antigravity/skills - run agentrun sync-antigravity\\n'
        failed=1
    fi
    return "$failed"
}
"""

if "antigravity_hooks_manifest()" not in content:
    idx = content.find("command_validate()")
    content = content[:idx] + antigravity_code + "\n" + content[idx:]

# Insert into command_validate path list
if "agents/antigravity/hooks.manifest.json \\" not in content:
    content = content.replace(
        "        agents/antigravity/AGENTS.md \\",
        "        agents/antigravity/AGENTS.md \\\n        agents/antigravity/hooks.manifest.json \\\n        agents/antigravity/hooks.json \\"
    )

# Insert validate_antigravity_sync into command_validate
if "validate_antigravity_sync || missing=1" not in content:
    content = content.replace(
        "    validate_codex_sync || missing=1",
        "    validate_codex_sync || missing=1\n    validate_antigravity_sync || missing=1"
    )

# Insert sync-antigravity into main case
if "sync-antigravity)" not in content:
    content = content.replace(
        "        sync-claude) command_sync_claude \"$@\" ;;",
        "        sync-claude) command_sync_claude \"$@\" ;;\n        sync-antigravity) command_sync_antigravity \"$@\" ;;"
    )

path.write_text(content)
