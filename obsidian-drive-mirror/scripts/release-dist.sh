#!/usr/bin/env bash
# Build, test and publish a release to the private BRAT distribution repo (DESIGN D-1).
# Uses the caller's own `gh` auth; no PAT is stored anywhere in my-env.
set -euo pipefail
cd "$(dirname "$0")/.."
DIST_REPO="${DIST_REPO:-Lzh-Function/drive-mirror}"

VERSION=$(node -p 'require("./manifest.json").version')
PKG_VERSION=$(node -p 'require("./package.json").version')
MIN_APP=$(node -p 'require("./manifest.json").minAppVersion')
[[ "$VERSION" == "$PKG_VERSION" ]] || { echo "manifest.json ($VERSION) != package.json ($PKG_VERSION)" >&2; exit 1; }
[[ "$(node -p "require('./versions.json')['$VERSION'] ?? ''")" == "$MIN_APP" ]] || { echo "versions.json lacks $VERSION -> $MIN_APP" >&2; exit 1; }
[[ -z "$(git status --porcelain -- .)" ]] || { echo "Uncommitted changes under $(pwd); commit first so the release maps to a source commit" >&2; exit 1; }
if gh release view "$VERSION" --repo "$DIST_REPO" >/dev/null 2>&1; then echo "Release $VERSION already exists in $DIST_REPO" >&2; exit 1; fi

npm ci
npm run lint
npm run typecheck
npm test
npm run build

SRC_COMMIT=$(git rev-parse HEAD)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
gh repo clone "$DIST_REPO" "$WORK/dist" -- --quiet
cp manifest.json versions.json "$WORK/dist/"
cp dist-README.md "$WORK/dist/README.md"
git -C "$WORK/dist" add manifest.json versions.json README.md
if ! git -C "$WORK/dist" diff --cached --quiet; then
  git -C "$WORK/dist" commit -q -m "Release $VERSION (source my-env@${SRC_COMMIT:0:12})"
  git -C "$WORK/dist" push -q origin HEAD
fi
gh release create "$VERSION" main.js manifest.json styles.css \
  --repo "$DIST_REPO" --title "$VERSION" \
  --notes "Built from my-env@$SRC_COMMIT (obsidian-drive-mirror/)."
echo "Released $VERSION to $DIST_REPO"
