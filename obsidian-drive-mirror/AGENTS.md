# AGENTS.md — obsidian-drive-mirror

Read `DESIGN.md` first; §0 (ADR-000) and §0.1 (v1.2 decisions D-1…D-15) override the rest of the document.

## Hard rules

- No Google OAuth, Google API keys, Drive API calls, or Google client libraries anywhere. `tests/unit/compliance.test.ts` enforces this.
- `RemoteReadProvider` has no mutating methods. Do not add any.
- The bridge only serves GET/HEAD, binds to loopback, never writes under the root, never follows symlinks, and never accepts paths from clients (opaque IDs only).
- The bridge root must be the read-only bind mount; keep `requireReadOnlyRoot` true. Read files only through `openInsideRoot` (bridge/src/safeOpen.ts), never by path after a check.
- Prune runs only after a complete validated manifest, all downloads verified, no failures, not cancelled. Never add a "delete all and re-download" shortcut.
- Never touch `configDir` (`.obsidian`) or any hidden path, except the plugin's own `staging/` and `state.json`.
- Plugin code (`src/`) must not import Node or Electron modules (lint + test enforce). Use `requestUrl`, the DataAdapter and pure JS.
- Never log tokens, Authorization headers, or note contents. Reports are content-free.
- Do not claim anything works on iOS until it has been checked on a device. Record device checks in README §9 (検証状況).

## Workflow

```bash
npm ci
npm run lint && npm run typecheck && npm test && npm run build
```

- Add or extend tests for every behaviour change: engine scenarios go in `tests/unit/engine.test.ts` (in-memory FS), bridge behaviour in `tests/bridge/`, end-to-end in `tests/integration/`.
- Keep PLAN and APPLY separate; dry run must stay side-effect free (no state write).
- Releases: `npm run release:dist` only (pushes to the private repo `Lzh-Function/drive-mirror`). Never put a PAT or token in this repo or in CI.

## Open device checks (P0 / P6 / P7)

1. Bridge `check` on the real `LLM-Wiki` (streaming mode, on-demand fetch time, drvfs mtime stability).
2. Windows → WSL localhost forwarding to `127.0.0.1:8787`; `tailscale serve` HTTPS reachable from the iPhone only.
3. Obsidian `requestUrl` on iOS: `Range` request header passes through and returns 206; response headers are present.
4. `DataAdapter.appendBinary` / `rename` / `rmdir` behave as in the in-memory FS on iOS; the file explorer reflects adapter-level changes without a restart.
5. `app.secretStorage` persists the token across restarts on iOS.
6. Hash time for the whole vault on the iPhone (strict mode cost shown in diagnostics).
