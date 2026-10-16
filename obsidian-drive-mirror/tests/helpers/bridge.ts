import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, realpathSync, writeFileSync } from "node:fs";
import type { AddressInfo } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import type { BridgeConfig } from "../../bridge/src/config";
import { createBridgeServer } from "../../bridge/src/server";
import { createSnapshotter, type Snapshotter } from "../../bridge/src/snapshot";
import type { HttpFn } from "../../src/provider/bridge";

export const TOKEN = "test-token-0123456789";
export const LOGIN = "me@example.com";

export function makeRoot(files: Record<string, string | Buffer>): string {
  const base = mkdtempSync(join(tmpdir(), "dm-bridge-"));
  const root = join(base, "LLM-Wiki");
  mkdirSync(join(root, ".obsidian"), { recursive: true });
  for (const [p, c] of Object.entries(files)) writeFile(root, p, c);
  return realpathSync(root);
}

export function writeFile(root: string, rel: string, content: string | Buffer): void {
  mkdirSync(dirname(join(root, rel)), { recursive: true });
  writeFileSync(join(root, rel), content);
}

export async function startBridge(
  root: string,
  opts: { cfg?: Partial<BridgeConfig>; sleep?: (ms: number) => Promise<void> } = {},
): Promise<{ url: string; close: () => Promise<void>; snapshots: Snapshotter; cfg: BridgeConfig }> {
  const cfg: BridgeConfig = {
    root,
    rootId: "rootid-test-0001",
    rootName: "LLM-Wiki",
    host: "127.0.0.1",
    port: 0,
    tokenSha256: createHash("sha256").update(TOKEN).digest("hex"),
    allowedTailscaleLogins: [LOGIN],
    requireTailscaleIdentity: true,
    requireMarker: ".obsidian",
    requireReadOnlyRoot: false, // temp dirs are writable; the read-only check has its own test
    stabilityDelayMs: 0,
    maxSnapshots: 4,
    stateDir: mkdtempSync(join(tmpdir(), "dm-state-")),
    ...opts.cfg,
  };
  const snapshots = await createSnapshotter(cfg, root, opts.sleep ?? (async () => {}));
  const server = createBridgeServer({ cfg, root, snapshots });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const { port } = server.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}`, snapshots, cfg, close: () => new Promise((r) => server.close(() => r())) };
}

/** HttpFn over fetch that injects the identity header Tailscale Serve would add. */
export function fetchHttp(login: string | null = LOGIN): HttpFn {
  return async (req) => {
    const res = await fetch(req.url, {
      method: req.method,
      headers: { ...req.headers, ...(login ? { "Tailscale-User-Login": login } : {}) },
    });
    const headers: Record<string, string> = {};
    res.headers.forEach((v, k) => (headers[k.toLowerCase()] = v));
    return { status: res.status, headers, body: await res.arrayBuffer() };
  };
}
