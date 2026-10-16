#!/usr/bin/env bash
# Copy build output (only) into the Windows test vault (DESIGN §11.2, D-12).
set -euo pipefail
cd "$(dirname "$0")/.."
TEST_VAULT="${TEST_VAULT:-/mnt/c/Users/TAKUH/Documents/DriveMirrorTest}"
[[ -d "$TEST_VAULT" ]] || { echo "Test vault not found: $TEST_VAULT (create it in Obsidian first, or set TEST_VAULT)" >&2; exit 1; }
case "$TEST_VAULT" in *GDrive*|/mnt/g*|/mnt/h*) echo "Refusing: test vault must not be inside Google Drive" >&2; exit 1;; esac
npm run build
DEST="$TEST_VAULT/.obsidian/plugins/drive-mirror"
mkdir -p "$DEST"
cp main.js manifest.json styles.css "$DEST/"
echo "Copied to $DEST — reload Obsidian (or toggle the plugin) to pick it up."
