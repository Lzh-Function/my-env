import { randomBytes } from "node:crypto";
import { rmSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { MirrorEngine } from "../../src/mirror/engine";
import { BridgeProvider } from "../../src/provider/bridge";
import { MemFs, MemStore } from "../helpers/memfs";
import { TOKEN, fetchHttp, makeRoot, startBridge, writeFile } from "../helpers/bridge";

let closers: (() => Promise<void>)[] = [];
afterEach(async () => {
  await Promise.all(closers.map((c) => c()));
  closers = [];
});

describe("engine ↔ bridge end to end", () => {
  it("mirrors a directory, including a multi-chunk file, and converges after remote and local changes", async () => {
    const big = randomBytes(1_000_003);
    const root = makeRoot({ "Index.md": "# index", "Notes/日本語.md": "本文", "Assets/big.bin": big });
    const b = await startBridge(root);
    closers.push(b.close);

    const fs = new MemFs();
    const provider = new BridgeProvider(fetchHttp(), {
      baseUrl: b.url,
      token: TOKEN,
      retry: { attempts: 1, baseDelayMs: 0, maxDelayMs: 0 },
    });
    const engine = new MirrorEngine({
      fs,
      provider,
      store: new MemStore(),
      configDir: ".obsidian",
      internalDir: ".obsidian/plugins/drive-mirror",
      settings: {
        maxFileSizeBytes: 512 * 1024 * 1024,
        deleteThresholdCount: 20,
        deleteThresholdRatio: 0.2,
        allowNonEmptyInit: false,
        chunkSizeBytes: 64 * 1024,
        concurrency: 2,
        readbackVerifyLimitBytes: 32 * 1024 * 1024,
      },
    });
    const approve = { approve: async () => true };

    expect((await provider.verifyRoot()).name).toBe("LLM-Wiki");
    const first = await engine.run(approve);
    expect(first.report.status).toBe("SUCCESS");
    expect(Buffer.from(fs.files.get("Assets/big.bin")!).equals(big)).toBe(true);
    expect(fs.text("Notes/日本語.md")).toBe("本文");

    writeFile(root, "Index.md", "# index v2");
    rmSync(join(root, "Notes"), { recursive: true });
    fs.put("phone-only.md", "local");
    fs.put("Assets/big.bin", "corrupted");
    const second = await engine.run(approve);
    expect(second.report.status).toBe("SUCCESS");
    expect([...fs.files.keys()].filter((p) => !p.startsWith(".")).sort()).toEqual(["Assets/big.bin", "Index.md"]);
    expect(fs.text("Index.md")).toBe("# index v2");
    expect(Buffer.from(fs.files.get("Assets/big.bin")!).equals(big)).toBe(true);
  });

  it("surfaces auth errors without retrying and without touching local files", async () => {
    const root = makeRoot({ "a.md": "a" });
    const b = await startBridge(root);
    closers.push(b.close);
    const fs = new MemFs();
    fs.put("keep.md", "k");
    const engine = new MirrorEngine({
      fs,
      provider: new BridgeProvider(fetchHttp("intruder@example.com"), { baseUrl: b.url, token: TOKEN }),
      store: new MemStore(),
      configDir: ".obsidian",
      internalDir: ".obsidian/plugins/drive-mirror",
      settings: {
        maxFileSizeBytes: 1e9,
        deleteThresholdCount: 20,
        deleteThresholdRatio: 0.2,
        allowNonEmptyInit: true,
        chunkSizeBytes: 1e6,
        concurrency: 2,
        readbackVerifyLimitBytes: 1e6,
      },
    });
    const { report } = await engine.run({ approve: async () => true });
    expect(report.status).toBe("FAILED");
    expect(report.failures[0]?.code).toBe("auth");
    expect(fs.text("keep.md")).toBe("k");
  });
});
