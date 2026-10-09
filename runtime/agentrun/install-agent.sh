#!/usr/bin/env bash
# Capsule 内で選択した agent の最新公開版をインストールする。
# stdout は PATH に追加する bin directory だけ（呼び出し側で $(...) する）。
set -euo pipefail

agent="${1:?usage: install-agent.sh AGENT [RUN_DIR [CACHE_DIR]]}"
run_dir="${2:-/runs}"
cache_dir="${3:-/cache}"
case "$agent" in
    claude) url=https://claude.ai/install.sh; cli=claude ;;
    codex) url=https://chatgpt.com/codex/install.sh; cli=codex ;;
    antigravity) url=https://antigravity.google/cli/install.sh; cli=agy ;;
    *) printf 'unknown agent: %s\n' "$agent" >&2; exit 2 ;;
esac

mkdir -p "$run_dir/live" "$run_dir/artifacts" "$cache_dir"
run_dir="$(cd "$run_dir" && pwd -P)"
cache_dir="$(cd "$cache_dir" && pwd -P)"
log="$run_dir/live/agent_install.log"
trap 'rc=$?; if [ "$rc" -ne 0 ]; then printf "latest %s installation failed (exit %s); see %s\n" "$agent" "$rc" "$log" >&2; fi' EXIT
umask 077
# 既存バイナリで installer が更新を省略しないよう、起動ごとに空の HOME。
# auth/config/session 用の /home/sandbox は installer に使わない。
tool_root="$(mktemp -d "$cache_dir/agent-cli.XXXXXX")"
tool_home="$tool_root/home"
bin_dir="$tool_home/.local/bin"
mkdir -p "$bin_dir"
# project の設定を installer が読み込まないよう、空の作業場所から実行。
cd "$tool_home"
printf 'Installing latest %s before startup...\n' "$agent" >&2
printf '\n[%s] agent=%s release=latest\n' "$(date -Iseconds)" "$agent" >> "$log"
curl --fail --silent --show-error --location --retry 2 --connect-timeout 20 --max-time 120 \
    "$url" -o "$tool_root/install.sh" >> "$log" 2>&1

# HOME/XDG の変更は installer の子 process に限定する。
installer_env=(HOME="$tool_home" XDG_CONFIG_HOME="$tool_home/.config"
    XDG_CACHE_HOME="$tool_home/.cache" XDG_DATA_HOME="$tool_home/.local/share")
case "$agent" in
    claude)
        timeout --foreground 600 env "${installer_env[@]}" bash "$tool_root/install.sh" latest \
            </dev/null >> "$log" 2>&1 ;;
    codex)
        timeout --foreground 600 env "${installer_env[@]}" CODEX_HOME="$tool_home/.codex" \
            CODEX_INSTALL_DIR="$bin_dir" CODEX_RELEASE=latest CODEX_NON_INTERACTIVE=1 \
            CODEX_INSTALL_DAEMON_ONLY=0 CODEX_INSTALL_DEFER_SELECTION=0 \
            sh "$tool_root/install.sh" </dev/null >> "$log" 2>&1 ;;
    antigravity)
        timeout --foreground 600 env "${installer_env[@]}" bash "$tool_root/install.sh" --dir "$bin_dir" \
            </dev/null >> "$log" 2>&1 ;;
esac

# PATH 上の image 内旧版ではなく、今回インストールした実体を検証する。
test -x "$bin_dir/$cli"
version="$(timeout --foreground 30 "$bin_dir/$cli" --version </dev/null 2>> "$log")"
test -n "$version"
python3 - "$run_dir/artifacts/agent-cli.json" "$agent" "$cli" "$bin_dir/$cli" "$version" "$url" "$tool_root/install.sh" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

output, agent, command, path, version, url, installer = sys.argv[1:]
Path(output).write_text(json.dumps({
    "agent": agent, "command": command, "path": path, "version": version,
    "requested_release": "latest", "installer_url": url,
    "installer_sha256": hashlib.sha256(Path(installer).read_bytes()).hexdigest(),
    "installed_at": datetime.now(timezone.utc).isoformat(),
}, ensure_ascii=False, indent=2) + "\n")
PY
printf 'Using %s\n' "$version" >&2
printf '%s\n' "$bin_dir"
