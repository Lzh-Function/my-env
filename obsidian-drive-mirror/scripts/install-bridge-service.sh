#!/usr/bin/env bash
# Install the bridge as a systemd *user* service pointing at this checkout (DESIGN D-6).
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd)
NODE=$(command -v node) || { echo "node not found in PATH" >&2; exit 1; }
CONFIG="${CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/drive-mirror-bridge/config.json}"
[[ -f "$CONFIG" ]] || { echo "No bridge config at $CONFIG; run 'node dist/bridge/cli.mjs init ...' first" >&2; exit 1; }
[[ -f dist/bridge/cli.mjs ]] || npm run build

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/drive-mirror-bridge.service" <<UNIT_EOF
[Unit]
Description=Drive Mirror read-only bridge (127.0.0.1 only; exposed via Windows tailscale serve)

[Service]
Type=simple
ExecStart=$NODE $REPO/dist/bridge/cli.mjs serve --config $CONFIG
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=yes

[Install]
WantedBy=default.target
UNIT_EOF

systemctl --user daemon-reload
systemctl --user enable drive-mirror-bridge
systemctl --user restart drive-mirror-bridge
# Start the user manager at boot even without an interactive WSL session.
if [[ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != yes ]]; then
  loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER"
fi
sleep 1
systemctl --user --no-pager status drive-mirror-bridge | head -5
echo "Logs: journalctl --user -u drive-mirror-bridge -f"
