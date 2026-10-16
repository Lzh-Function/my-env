import { createHash, timingSafeEqual } from "node:crypto";
import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";
import type { BridgeConfig } from "./config";
import { openInsideRoot } from "./safeOpen";
import { IncompleteError, type Snapshotter } from "./snapshot";

export const BRIDGE_VERSION = "0.1.0";

export interface ServerDeps {
  cfg: BridgeConfig;
  root: string; // realpath of cfg.root
  snapshots: Snapshotter;
  log?: (line: string) => void;
}

function send(res: ServerResponse, status: number, body: unknown, headers: Record<string, string> = {}): void {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": String(Buffer.byteLength(json)),
    ...headers,
  });
  res.end(json);
}

/** Parse a single `bytes=a-b` / `bytes=a-` range. Returns null for no header, "invalid" when unsatisfiable. */
export function parseRange(header: string | undefined, size: number): { start: number; end: number } | null | "invalid" {
  if (header === undefined) return null;
  const m = /^bytes=(\d+)-(\d*)$/.exec(header.trim());
  if (!m) return "invalid";
  const start = Number(m[1]);
  const end = m[2] === "" ? size - 1 : Math.min(Number(m[2]), size - 1);
  if (!Number.isSafeInteger(start) || start >= size || end < start) return "invalid";
  return { start, end };
}

export function createBridgeServer({ cfg, root, snapshots, log = () => {} }: ServerDeps): Server {
  const expected = Buffer.from(cfg.tokenSha256, "hex");
  const allowed = new Set(cfg.allowedTailscaleLogins.map((l) => l.toLowerCase()));
  let authFailures: number[] = [];

  function authorize(req: IncomingMessage): { ok: true } | { ok: false; status: number; error: string } {
    const now = Date.now();
    authFailures = authFailures.filter((t) => now - t < 60_000);
    if (authFailures.length >= 20) return { ok: false, status: 429, error: "too_many_auth_failures" };
    const m = /^Bearer (\S+)$/.exec(req.headers.authorization ?? "");
    const given = createHash("sha256").update(m?.[1] ?? "").digest();
    if (!m || !timingSafeEqual(given, expected)) {
      authFailures.push(now);
      return { ok: false, status: 401, error: "unauthorized" };
    }
    if (cfg.requireTailscaleIdentity) {
      const login = req.headers["tailscale-user-login"];
      if (typeof login !== "string" || !allowed.has(login.toLowerCase())) {
        authFailures.push(now);
        return { ok: false, status: 403, error: "tailscale_identity_not_allowed" };
      }
    }
    return { ok: true };
  }

  async function serveFile(req: IncomingMessage, res: ServerResponse, id: string): Promise<void> {
    const rec = snapshots.lookup(id);
    if (!rec) return send(res, 409, { error: "unknown_or_expired" });
    let opened;
    try {
      // Verified descriptor: no symlink/junction anywhere in the chain, no TOCTOU between check and read.
      opened = await openInsideRoot(root, rec.path);
    } catch {
      return send(res, 409, { error: "changed" });
    }
    const { fh, stats: st } = opened;
    if (st.size !== rec.size || st.mtimeMs !== rec.mtimeMs) {
      await fh.close();
      return send(res, 409, { error: "changed" });
    }

    const common = {
      "Content-Type": "application/octet-stream",
      "Accept-Ranges": "bytes",
      ETag: `"${rec.sha256}"`,
      "X-Content-SHA256": rec.sha256,
    };
    if (rec.size === 0) {
      await fh.close();
      res.writeHead(200, { ...common, "Content-Length": "0" });
      return void res.end();
    }
    const range = parseRange(req.headers.range, rec.size);
    if (range === "invalid") {
      await fh.close();
      return send(res, 416, { error: "bad_range" }, { "Content-Range": `bytes */${rec.size}` });
    }
    const { start, end } = range ?? { start: 0, end: rec.size - 1 };
    res.writeHead(range ? 206 : 200, {
      ...common,
      "Content-Length": String(end - start + 1),
      ...(range ? { "Content-Range": `bytes ${start}-${end}/${rec.size}` } : {}),
    });
    if (req.method === "HEAD") {
      await fh.close();
      return void res.end();
    }
    const stream = fh.createReadStream({ start, end, autoClose: true });
    stream.on("error", () => res.destroy());
    res.on("close", () => stream.destroy());
    stream.pipe(res);
  }

  async function handle(req: IncomingMessage, res: ServerResponse): Promise<void> {
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    const url = new URL(req.url ?? "/", "http://bridge.invalid");
    if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, { error: "read_only" }, { Allow: "GET, HEAD" });
    if (url.pathname === "/v1/health") return send(res, 200, { ok: true, version: BRIDGE_VERSION });

    const auth = authorize(req);
    if (!auth.ok) return send(res, auth.status, { error: auth.error });

    if (url.pathname === "/v1/root") {
      return send(res, 200, { rootIdentity: { rootId: cfg.rootId, name: cfg.rootName } });
    }
    if (url.pathname === "/v1/manifest") {
      try {
        const snap = await snapshots.build();
        return send(res, 200, {
          schemaVersion: 1,
          snapshotId: snap.snapshotId,
          complete: true,
          generatedAt: snap.generatedAt,
          rootIdentity: { rootId: cfg.rootId, name: cfg.rootName },
          entries: snap.files.map((f) => ({
            id: f.id,
            path: f.path,
            size: f.size,
            modifiedTime: new Date(f.mtimeMs).toISOString(),
            sha256: f.sha256,
          })),
          excluded: snap.excluded,
        });
      } catch (e) {
        if (e instanceof IncompleteError) {
          return send(res, 503, { complete: false, error: "incomplete", problems: e.problems.slice(0, 50) }, { "Retry-After": "30" });
        }
        throw e;
      }
    }
    const fm = /^\/v1\/file\/([A-Za-z0-9_-]{1,64})$/.exec(url.pathname);
    if (fm) return serveFile(req, res, fm[1]!);
    return send(res, 404, { error: "not_found" });
  }

  return createServer((req, res) => {
    const t0 = Date.now();
    res.on("finish", () => {
      // No tokens, paths or contents in logs.
      const route = (req.url ?? "").replace(/^(\/v1\/file\/).*/, "$1:id").replace(/\?.*$/, "");
      log(`${req.method} ${route} ${res.statusCode} ${Date.now() - t0}ms`);
    });
    handle(req, res).catch((e: unknown) => {
      log(`internal error: ${(e as Error).message}`);
      if (!res.headersSent) send(res, 500, { error: "internal" });
      else res.destroy();
    });
  });
}
