#!/usr/bin/env bash
# P0 checks on the PC side (DESIGN §12 P0, §14-1/2). Read-only; prints what to verify by hand.
set -uo pipefail
cd "$(dirname "$0")/.."
SRC="${SRC:-$HOME/workspace/GDrive/マイドライブ/LLM-Wiki}"
ROOT="${ROOT:-/srv/drivemirror/vault}"
CONFIG="${CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/drive-mirror-bridge/config.json}"
ok() { printf '  [ok] %s\n' "$*"; }
ng() { printf '  [NG] %s\n' "$*"; FAIL=1; }
FAIL=0

echo "1. Drive for desktop mount"
mountpoint -q "$HOME/workspace/GDrive" && ok "~/workspace/GDrive is mounted" || ng "~/workspace/GDrive is not a mountpoint"
[[ -d "$SRC/.obsidian" ]] && ok "vault marker found: $SRC/.obsidian" || ng "no .obsidian under $SRC"
[[ -d "$ROOT/.obsidian" ]] && ok "read-only view populated: $ROOT" || ng "no .obsidian under $ROOT (run scripts/install-ro-mount.sh)"
findmnt -n -o OPTIONS --target "$ROOT" 2>/dev/null | tr ',' '\n' | grep -qx ro && ok "$ROOT is mounted read-only" || ng "$ROOT is not a read-only mount"

echo "2. Bridge build + config"
[[ -f dist/bridge/cli.mjs ]] || npm run build >/dev/null
[[ -f "$CONFIG" ]] && ok "config: $CONFIG" || ng "no config; run: node dist/bridge/cli.mjs init --root \"$ROOT\" --name LLM-Wiki --login <tailscale-login>"
[[ -f "$CONFIG" ]] && [[ "$(stat -c %a "$CONFIG")" == "600" ]] && ok "config mode 600" || true

echo "3. Snapshot (two stability scans + hashing; first run reads every file)"
if [[ -f "$CONFIG" ]]; then
  node dist/bridge/cli.mjs check --config "$CONFIG" && ok "complete snapshot" || ng "snapshot incomplete (see problems above)"
fi

echo "4. Local service"
if [[ -f "$CONFIG" ]]; then
  PORT=$(node -p "require('$CONFIG').port")
  curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null && ok "bridge answering on 127.0.0.1:$PORT" || ng "bridge not running (systemctl --user status drive-mirror-bridge)"
  ss -ltn "sport = :$PORT" | grep -q "127.0.0.1:$PORT" && ok "bound to loopback only" || ng "not bound to 127.0.0.1:$PORT"
fi

cat <<MSG

Manual checks (Windows / iPhone):
  a. Windows PowerShell:  curl.exe http://127.0.0.1:${PORT:-8787}/v1/health   (WSL localhost forwarding)
  b. Windows PowerShell:  tailscale serve --bg --https=8443 http://127.0.0.1:${PORT:-8787}
                          tailscale serve status
  c. Tailnet policy: grant only your iPhone -> this PC on tcp:8443 (see README "Tailscale ACL").
  d. iPhone Safari (Tailscale ON):  https://<pc>.<tailnet>.ts.net:8443/v1/health  -> {"ok":true}
  e. iPhone Safari (Tailscale OFF): the same URL must NOT load.
MSG
exit $FAIL
