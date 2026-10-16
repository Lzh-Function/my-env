import { sha256Hex } from "../util/hash";
import { ProviderError, type RemoteEntry, type RemoteManifest, type RemoteReadProvider, type RootIdentity } from "./types";

/**
 * In-memory provider for unit tests and for trying the plugin in a desktop test vault without a bridge.
 * `files` can be mutated between syncs to simulate remote changes.
 */
export class MockProvider implements RemoteReadProvider {
  readonly kind = "mock";
  readonly files = new Map<string, Uint8Array>();
  rootIdentity: RootIdentity = { rootId: "mock-root", name: "Mock Vault" };
  /** Test hooks. */
  failList: ProviderError | null = null;
  failRead: (path: string) => ProviderError | null = () => null;
  excluded: Record<string, number> = {};
  private snapshot = 0;
  private live = new Map<string, { path: string; data: Uint8Array }>();

  constructor(initial: Record<string, string | Uint8Array> = {}) {
    for (const [p, v] of Object.entries(initial)) this.set(p, v);
  }

  set(path: string, content: string | Uint8Array): void {
    this.files.set(path, typeof content === "string" ? new TextEncoder().encode(content) : content);
  }

  async verifyRoot(): Promise<RootIdentity> {
    return this.rootIdentity;
  }

  async listCompleteTree(): Promise<RemoteManifest> {
    if (this.failList) throw this.failList;
    const snapshotId = `s${++this.snapshot}`;
    this.live = new Map();
    const entries: RemoteEntry[] = [];
    for (const [path, data] of [...this.files.entries()].sort(([a], [b]) => a.localeCompare(b))) {
      const id = `${snapshotId}-${entries.length}`;
      this.live.set(id, { path, data });
      entries.push({ id, path, size: data.byteLength, modifiedTime: null, sha256: sha256Hex(data) });
    }
    return {
      schemaVersion: 1,
      snapshotId,
      complete: true,
      generatedAt: new Date(0).toISOString(),
      rootIdentity: this.rootIdentity,
      entries,
      excluded: { ...this.excluded },
    };
  }

  async readRange(entry: RemoteEntry, start: number, end: number): Promise<ArrayBuffer> {
    const injected = this.failRead(entry.path);
    if (injected) throw injected;
    const live = this.live.get(entry.id);
    if (!live) throw new ProviderError("conflict", "unknown_or_expired", 409);
    const data = live.data.slice(start, end);
    return data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength) as ArrayBuffer;
  }

  async signOut(): Promise<void> {}
}

/** Small fixed tree for the desktop "mock" provider option. */
export function demoMockProvider(): MockProvider {
  return new MockProvider({
    "Welcome.md": "# Drive Mirror (mock)\n\nThis vault is a read-only mirror. Local edits are discarded on sync.\n",
    "Notes/Alpha.md": "Alpha note\n",
    "Notes/日本語ノート.md": "日本語の内容\n",
    "Assets/blob.bin": new Uint8Array(Array.from({ length: 300_000 }, (_, i) => i % 251)),
  });
}
