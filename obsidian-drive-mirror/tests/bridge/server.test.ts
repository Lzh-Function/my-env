import { symlinkSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { parseRange } from "../../bridge/src/server";
import { validateConfig } from "../../bridge/src/config";
import { LOGIN, TOKEN, makeRoot, startBridge, writeFile } from "../helpers/bridge";

const auth = { Authorization: `Bearer ${TOKEN}`, "Tailscale-User-Login": LOGIN };
let closers: (() => Promise<void>)[] = [];
afterEach(async () => {
  await Promise.all(closers.map((c) => c()));
  closers = [];
});

async function bridge(files: Record<string, string>, opts: Parameters<typeof startBridge>[1] = {}) {
  const root = makeRoot(files);
  const b = await startBridge(root, opts);
  closers.push(b.close);
  return { root, ...b };
}

async function manifest(url: string, headers: Record<string, string> = auth) {
  const res = await fetch(`${url}/v1/manifest`, { headers });
  return { status: res.status, body: (await res.json()) as Record<string, any> };
}

describe("bridge server", () => {
  it("health is public but everything else needs bearer + tailscale identity", async () => {
    const { url } = await bridge({ "a.md": "a" });
    expect((await fetch(`${url}/v1/health`)).status).toBe(200);
    expect((await manifest(url, {})).status).toBe(401);
    expect((await manifest(url, { ...auth, Authorization: "Bearer wrong" })).status).toBe(401);
    expect((await manifest(url, { Authorization: auth.Authorization })).status).toBe(403);
    expect((await manifest(url, { ...auth, "Tailscale-User-Login": "evil@example.com" })).status).toBe(403);
    expect((await manifest(url)).status).toBe(200);
  });

  it("is read-only", async () => {
    const { url } = await bridge({ "a.md": "a" });
    for (const method of ["POST", "PUT", "DELETE", "PATCH"]) {
      expect((await fetch(`${url}/v1/manifest`, { method, headers: auth })).status).toBe(405);
    }
  });

  it("lists files with hashes and counts exclusions; skips hidden, symlinks and Google-native files", async () => {
    const { url, root } = await bridge({
      "a.md": "alpha",
      "d/b.md": "b",
      "d/.gitkeep": "",
      "doc.gdoc": "{}",
      "cap/remote-capture:abc/packet.yml": "x",
    });
    symlinkSync(join(root, "a.md"), join(root, "link.md"));
    symlinkSync("/etc", join(root, "etc-link"));
    const { status, body } = await manifest(url);
    expect(status).toBe(200);
    expect(body.complete).toBe(true);
    expect(body.entries.map((e: { path: string }) => e.path)).toEqual(["a.md", "d/b.md"]);
    expect(body.entries[0].sha256).toBe("8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8");
    expect(body.excluded).toEqual({ hidden: 2, symlink: 2, google_native: 1, unsupported_name: 1 });
  });

  it("refuses to claim completeness when the marker is missing, temp files exist, or the tree is unstable", async () => {
    const noMarker = await bridge({ "a.md": "a" }, { cfg: { requireMarker: ".missing" } });
    expect((await manifest(noMarker.url)).status).toBe(503);

    const temp = await bridge({ "a.md": "a", "~$draft.docx": "x" });
    const r = await manifest(temp.url);
    expect(r.status).toBe(503);
    expect(r.body.complete).toBe(false);

    let root = "";
    const unstable = await bridge(
      { "a.md": "a" },
      { sleep: async () => writeFile(root, "new.md", "appeared between scans") },
    );
    root = unstable.root;
    expect((await manifest(unstable.url)).status).toBe(503);
  });

  it("refuses a writable root when requireReadOnlyRoot is set", async () => {
    const { url } = await bridge({ "a.md": "a" }, { cfg: { requireReadOnlyRoot: true } });
    const r = await manifest(url);
    expect(r.status).toBe(503);
    expect(r.body.problems[0]).toMatch(/writable/);
  });

  it("does not follow a symlink or FIFO swapped in for a listed file", async () => {
    const { url, root } = await bridge({ "a.md": "a", "b.md": "b" });
    const ids = (await manifest(url)).body.entries.map((e: { id: string }) => e.id);
    const { rmSync } = await import("node:fs");
    const { execFileSync } = await import("node:child_process");
    rmSync(join(root, "a.md"));
    symlinkSync("/etc/hostname", join(root, "a.md"));
    rmSync(join(root, "b.md"));
    execFileSync("mkfifo", [join(root, "b.md")]);
    expect((await fetch(`${url}/v1/file/${ids[0]}`, { headers: auth })).status).toBe(409);
    expect((await fetch(`${url}/v1/file/${ids[1]}`, { headers: auth, signal: AbortSignal.timeout(3000) })).status).toBe(409);
  });

  it("serves ranges and rejects files changed since the snapshot", async () => {
    const { url, root } = await bridge({ "a.md": "0123456789" });
    const { body } = await manifest(url);
    const id = body.entries[0].id as string;
    const part = await fetch(`${url}/v1/file/${id}`, { headers: { ...auth, Range: "bytes=2-5" } });
    expect(part.status).toBe(206);
    expect(await part.text()).toBe("2345");
    expect(part.headers.get("content-range")).toBe("bytes 2-5/10");
    expect(part.headers.get("x-content-sha256")).toBe(body.entries[0].sha256);

    const bad = await fetch(`${url}/v1/file/${id}`, { headers: { ...auth, Range: "bytes=50-60" } });
    expect(bad.status).toBe(416);

    writeFile(root, "a.md", "0123456789-changed");
    expect((await fetch(`${url}/v1/file/${id}`, { headers: auth })).status).toBe(409);
    utimesSync(join(root, "a.md"), new Date(), new Date());
  });

  it("rejects unknown ids and anything that looks like a path", async () => {
    const { url } = await bridge({ "a.md": "a" });
    expect((await fetch(`${url}/v1/file/nope`, { headers: auth })).status).toBe(409);
    expect((await fetch(`${url}/v1/file/..%2F..%2Fetc%2Fpasswd`, { headers: auth })).status).toBe(404);
    expect((await fetch(`${url}/v1/file/a/b`, { headers: auth })).status).toBe(404);
  });

  it("expires ids from old snapshots", async () => {
    const { url } = await bridge({ "a.md": "a" }, { cfg: { maxSnapshots: 1 } });
    const first = (await manifest(url)).body.entries[0].id;
    await manifest(url);
    expect((await fetch(`${url}/v1/file/${first}`, { headers: auth })).status).toBe(409);
  });

  it("does not follow a symlinked parent swapped in after listing", async () => {
    const { url, root } = await bridge({ "d/a.md": "a" });
    const id = (await manifest(url)).body.entries[0].id;
    const { renameSync } = await import("node:fs");
    renameSync(join(root, "d"), join(root, "d-real"));
    symlinkSync(join(root, "d-real"), join(root, "d"));
    expect((await fetch(`${url}/v1/file/${id}`, { headers: auth })).status).toBe(409);
  });
});

describe("bridge config & range parsing", () => {
  it("rejects non-loopback hosts and stateDir inside root", () => {
    const base = {
      root: "/v",
      rootId: "abcdefgh12",
      rootName: "v",
      host: "0.0.0.0",
      port: 8787,
      tokenSha256: "a".repeat(64),
      allowedTailscaleLogins: ["x"],
      requireTailscaleIdentity: true,
      requireMarker: ".obsidian",
      requireReadOnlyRoot: true,
      stabilityDelayMs: 0,
      maxSnapshots: 4,
      stateDir: "/v/.state",
    };
    expect(() => validateConfig(base)).toThrow(/loopback[\s\S]*stateDir/);
  });

  it("parses ranges", () => {
    expect(parseRange(undefined, 10)).toBeNull();
    expect(parseRange("bytes=0-", 10)).toEqual({ start: 0, end: 9 });
    expect(parseRange("bytes=3-100", 10)).toEqual({ start: 3, end: 9 });
    expect(parseRange("bytes=10-", 10)).toBe("invalid");
    expect(parseRange("bytes=1-2,4-5", 10)).toBe("invalid");
  });
});
