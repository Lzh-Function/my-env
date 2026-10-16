import { beforeEach, describe, expect, it } from "vitest";
import { MirrorEngine, type EngineSettings } from "../../src/mirror/engine";
import { MockProvider } from "../../src/provider/mock";
import { ProviderError } from "../../src/provider/types";
import { MemFs, MemStore } from "../helpers/memfs";

const CONFIG = ".obsidian";
const INTERNAL = ".obsidian/plugins/drive-mirror";

const settings: EngineSettings = {
  maxFileSizeBytes: 1024 * 1024,
  deleteThresholdCount: 20,
  deleteThresholdRatio: 0.2,
  allowNonEmptyInit: false,
  chunkSizeBytes: 7, // tiny chunks to exercise ranged downloads
  concurrency: 2,
  readbackVerifyLimitBytes: 1024 * 1024,
};

function setup(remote: Record<string, string>, opts: { caseInsensitive?: boolean; settings?: Partial<EngineSettings> } = {}) {
  const fs = new MemFs(opts.caseInsensitive);
  fs.put(`${INTERNAL}/data.json`, '{"bridgeToken":"secret"}');
  fs.put(`${CONFIG}/app.json`, "{}");
  const provider = new MockProvider(remote);
  const store = new MemStore();
  const engine = new MirrorEngine({
    fs,
    provider,
    store,
    configDir: CONFIG,
    internalDir: INTERNAL,
    settings: { ...settings, ...opts.settings },
    newId: () => "vault-1",
  });
  const approveAll = { approve: async () => true };
  return { fs, provider, store, engine, approveAll };
}

function managed(fs: MemFs): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of [...fs.files.keys()].sort()) if (!p.startsWith(".")) out[p] = fs.text(p)!;
  return out;
}

describe("MirrorEngine", () => {
  let t: ReturnType<typeof setup>;
  beforeEach(() => {
    t = setup({ "a.md": "alpha", "dir/b.md": "bravo bravo bravo", "dir/sub/c.bin": "c" });
  });

  it("initial sync downloads everything into an empty vault", async () => {
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("SUCCESS");
    expect(managed(t.fs)).toEqual({ "a.md": "alpha", "dir/b.md": "bravo bravo bravo", "dir/sub/c.bin": "c" });
    expect(t.store.state?.lastCompleteSyncAt).not.toBeNull();
    expect(t.store.state?.rootIdentity?.rootId).toBe("mock-root");
  });

  it("second sync with identical content downloads nothing", async () => {
    await t.engine.run(t.approveAll);
    const { report } = await t.engine.run(t.approveAll);
    expect(report.counts.unchanged).toBe(3);
    expect(report.bytesDownloaded).toBe(0);
    expect(report.applied).toEqual({ created: 0, replaced: 0, deleted: 0, foldersRemoved: 0 });
  });

  it("discards local edits even when size and remote are unchanged", async () => {
    await t.engine.run(t.approveAll);
    t.fs.put("a.md", "ALPHA"); // same length, different bytes
    const { report } = await t.engine.run(t.approveAll);
    expect(report.counts.localEdits).toBe(1);
    expect(t.fs.text("a.md")).toBe("alpha");
  });

  it("restores locally deleted files and deletes local-only files and folders", async () => {
    await t.engine.run(t.approveAll);
    await t.fs.remove("dir/b.md");
    t.fs.put("new/local-note.md", "mine");
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("SUCCESS");
    expect(managed(t.fs)).toEqual({ "a.md": "alpha", "dir/b.md": "bravo bravo bravo", "dir/sub/c.bin": "c" });
    expect(t.fs.folders.has("new")).toBe(false);
  });

  it("propagates remote changes, deletions and renames", async () => {
    await t.engine.run(t.approveAll);
    t.provider.set("a.md", "alpha v2");
    t.provider.files.delete("dir/sub/c.bin");
    t.provider.files.delete("dir/b.md");
    t.provider.set("moved/b.md", "bravo bravo bravo");
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("SUCCESS");
    expect(managed(t.fs)).toEqual({ "a.md": "alpha v2", "moved/b.md": "bravo bravo bravo" });
    expect(t.fs.folders.has("dir")).toBe(false);
  });

  it("deletes a re-created file that was deleted remotely", async () => {
    await t.engine.run(t.approveAll);
    t.provider.files.delete("a.md");
    await t.engine.run(t.approveAll);
    t.fs.put("a.md", "recreated on phone");
    await t.engine.run(t.approveAll);
    expect(t.fs.files.has("a.md")).toBe(false);
  });

  it("never touches .obsidian, plugin data or hidden files", async () => {
    t.provider.set("visible.md", "v");
    await t.engine.run(t.approveAll);
    t.fs.put(".trash/x.md", "trash");
    t.fs.put("dir/.hidden", "h");
    await t.engine.run(t.approveAll);
    expect(t.fs.text(`${INTERNAL}/data.json`)).toBe('{"bridgeToken":"secret"}');
    expect(t.fs.text(`${CONFIG}/app.json`)).toBe("{}");
    expect(t.fs.text(".trash/x.md")).toBe("trash");
    expect(t.fs.text("dir/.hidden")).toBe("h");
  });

  it("does not delete anything when the remote listing fails", async () => {
    await t.engine.run(t.approveAll);
    t.provider.failList = new ProviderError("incomplete", "drive not ready", 503);
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("FAILED");
    expect(Object.keys(managed(t.fs))).toHaveLength(3);
  });

  it("does not prune when any download fails, and keeps the old copy", async () => {
    await t.engine.run(t.approveAll);
    t.provider.set("a.md", "alpha v2");
    t.fs.put("local-only.md", "x");
    t.provider.failRead = (p) => (p === "a.md" ? new ProviderError("server", "boom", 500) : null);
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("FAILED");
    expect(t.fs.text("a.md")).toBe("alpha");
    expect(t.fs.files.has("local-only.md")).toBe(true);
    // recovers next time
    t.provider.failRead = () => null;
    expect((await t.engine.run(t.approveAll)).report.status).toBe("SUCCESS");
    expect(t.fs.text("a.md")).toBe("alpha v2");
    expect(t.fs.files.has("local-only.md")).toBe(false);
  });

  it("restores the previous file if placing the new one fails", async () => {
    await t.engine.run(t.approveAll);
    t.provider.set("a.md", "alpha v2");
    let failed = false;
    t.fs.failWrite = (p) => p === "a.md" && !failed && (failed = true);
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("FAILED");
    expect(t.fs.text("a.md")).toBe("alpha");
  });

  it("aborts without pruning on a 409 conflict", async () => {
    await t.engine.run(t.approveAll);
    t.fs.put("local-only.md", "x");
    t.provider.set("a.md", "alpha v2");
    t.provider.failRead = () => new ProviderError("conflict", "changed", 409);
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("FAILED");
    expect(report.failures[0]?.code).toBe("conflict");
    expect(t.fs.files.has("local-only.md")).toBe(true);
  });

  it("dry run changes nothing", async () => {
    t.fs.put("x.md", "x");
    const before = managed(t.fs);
    const { report, plan } = await t.engine.run({ dryRun: true });
    expect(report.status).toBe("DRY_RUN");
    expect(plan?.upserts).toHaveLength(3);
    expect(managed(t.fs)).toEqual(before);
    expect(t.store.state).toBeNull();
  });

  it("blocks the first sync into a non-empty vault", async () => {
    t.fs.put("existing.md", "do not lose me");
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("BLOCKED");
    expect(t.fs.text("existing.md")).toBe("do not lose me");
  });

  it("blocks when the bridge root identity changes", async () => {
    await t.engine.run(t.approveAll);
    t.provider.rootIdentity = { rootId: "other", name: "Other" };
    const { report } = await t.engine.run(t.approveAll);
    expect(report.status).toBe("BLOCKED");
    expect(report.failures[0]?.code).toBe("root_changed");
  });

  it("requires confirmation for mass deletion and for an emptied remote", async () => {
    const many: Record<string, string> = {};
    for (let i = 0; i < 30; i++) many[`n${i}.md`] = `${i}`;
    const m = setup(many);
    await m.engine.run(m.approveAll);
    for (let i = 0; i < 25; i++) m.provider.files.delete(`n${i}.md`);
    const unattended = await m.engine.run();
    expect(unattended.report.status).toBe("BLOCKED");
    expect(m.fs.files.size).toBeGreaterThan(30);

    let seen: string[] = [];
    const declined = await m.engine.run({ approve: async (p) => ((seen = p.confirmations), false) });
    expect(seen).toContain("mass_delete");
    expect(declined.report.status).toBe("CANCELLED");

    for (let i = 25; i < 30; i++) m.provider.files.delete(`n${i}.md`);
    const empty = await m.engine.run({ approve: async (p) => ((seen = p.confirmations), true) });
    expect(seen).toContain("remote_empty");
    expect(empty.report.status).toBe("SUCCESS");
    expect(Object.keys(managed(m.fs))).toHaveLength(0);
  });

  it("marks oversize files as PARTIAL without deleting the local copy", async () => {
    const b2 = setup({ "big.pdf": "x".repeat(100), "a.md": "a" }, { settings: { maxFileSizeBytes: 50 } });
    const { report } = await b2.engine.run(b2.approveAll);
    expect(report.status).toBe("PARTIAL");
    expect(report.counts.skippedOversize).toBe(1);
    expect(b2.fs.files.has("big.pdf")).toBe(false);
    expect(b2.store.state?.lastCompleteSyncAt).toBeNull();
  });

  it("downloads files larger than one chunk and verifies them", async () => {
    const payload = "0123456789".repeat(50);
    const c = setup({ "long.txt": payload });
    const { report } = await c.engine.run(c.approveAll);
    expect(report.status).toBe("SUCCESS");
    expect(c.fs.text("long.txt")).toBe(payload);
    expect([...c.fs.files.keys()].some((p) => p.includes("staging/") && p.endsWith(".part"))).toBe(false);
  });

  it("handles a local file where the remote needs a folder, and vice versa", async () => {
    await t.engine.run(t.approveAll);
    t.provider.files.delete("a.md");
    t.provider.set("a.md/inner.md", "now a folder"); // remote: a.md is a folder
    t.provider.files.delete("dir/sub/c.bin");
    t.provider.set("dir/sub", "now a file"); // remote: dir/sub is a file
    const { report } = await t.engine.run(t.approveAll);
    expect(report.failures).toEqual([]);
    expect(managed(t.fs)).toEqual({ "a.md/inner.md": "now a folder", "dir/b.md": "bravo bravo bravo", "dir/sub": "now a file" });
  });

  it("fixes case-only renames on a case-insensitive filesystem", async () => {
    const c = setup({ "Note.md": "n" }, { caseInsensitive: true });
    await c.engine.run(c.approveAll);
    c.provider.files.delete("Note.md");
    c.provider.set("NOTE.md", "n");
    const { report } = await c.engine.run(c.approveAll);
    expect(report.status).toBe("SUCCESS");
    expect(managed(c.fs)).toEqual({ "NOTE.md": "n" });
  });

  it("refuses concurrent runs", async () => {
    const p = t.engine.run(t.approveAll);
    await expect(t.engine.run(t.approveAll)).rejects.toThrow(/already running/);
    await p;
  });

  it("cancellation stops before pruning", async () => {
    await t.engine.run(t.approveAll);
    t.fs.put("local-only.md", "x");
    t.provider.set("a.md", "v2");
    const ac = new AbortController();
    const { report } = await t.engine.run({ signal: ac.signal, approve: async () => (ac.abort(), true) });
    expect(report.status).toBe("CANCELLED");
    expect(t.fs.files.has("local-only.md")).toBe(true);
  });

  it("reports contain no file contents or tokens", async () => {
    await t.engine.run(t.approveAll);
    const json = JSON.stringify(t.store.state);
    expect(json).not.toContain("bravo");
    expect(json).not.toContain("secret");
  });
});
