#!/usr/bin/env bash
# Expose the source vault to the bridge through a read-only bind mount (DESIGN D-15).
# Even a buggy or compromised bridge then cannot modify the Drive copy (writes fail with EROFS).
# Run as your normal user; it calls sudo for the system unit.
set -euo pipefail
SRC="${SRC:-$HOME/workspace/GDrive/マイドライブ/LLM-Wiki}"
DST="${DST:-/srv/drivemirror/vault}"

[[ -d "$SRC/.obsidian" ]] || { echo "Not a vault (no .obsidian): $SRC" >&2; exit 1; }
SRC_MOUNT=$(findmnt -n -o TARGET --target "$SRC")
SRC_UNIT=$(systemd-escape -p --suffix=mount "$SRC_MOUNT")
UNIT=$(systemd-escape -p --suffix=mount "$DST")
echo "source: $SRC  (on $SRC_MOUNT, $SRC_UNIT)"

# The Drive letter mount must survive WSL restarts, or the read-only view (and the bridge) silently disappears.
SRC_ORIGIN=$(systemctl show -p SourcePath --value "$SRC_UNIT" 2>/dev/null || true)
FRAGMENT=$(systemctl show -p FragmentPath --value "$SRC_UNIT" 2>/dev/null || true)
if [[ -z "$FRAGMENT" && ( -z "$SRC_ORIGIN" || "$SRC_ORIGIN" == /proc/self/mountinfo ) ]]; then
  echo "NG: $SRC_MOUNT was mounted by hand and will be gone after a WSL restart." >&2
  echo "    Add it to /etc/fstab first (see README \"WSL: Driveのマウントを永続化\"), then: sudo systemctl daemon-reload && sudo mount -a" >&2
  [[ "${FORCE:-0}" == 1 ]] || exit 1
  echo "    FORCE=1 given; continuing anyway." >&2
fi
echo "target: $DST  ($UNIT, read-only)"

sudo mkdir -p "$DST"
sudo tee "/etc/systemd/system/$UNIT" >/dev/null <<UNIT_EOF
[Unit]
Description=Read-only view of the Drive Mirror source vault
Requires=$SRC_UNIT
After=$SRC_UNIT

[Mount]
What=$SRC
Where=$DST
Type=none
Options=bind,ro

[Install]
WantedBy=multi-user.target
UNIT_EOF
sudo systemctl daemon-reload
sudo systemctl enable --now "$UNIT"

findmnt -n -o OPTIONS --target "$DST" | tr ',' '\n' | grep -qx ro || { echo "NG: $DST is not mounted read-only" >&2; exit 1; }
if touch "$DST/.drive-mirror-write-test" 2>/dev/null; then
  rm -f "$DST/.drive-mirror-write-test"; echo "NG: $DST is writable" >&2; exit 1
fi
echo "OK: $DST is a read-only bind mount. Use it as the bridge root:"
echo "  node dist/bridge/cli.mjs init --root $DST --name LLM-Wiki --login <tailscale-login>"
