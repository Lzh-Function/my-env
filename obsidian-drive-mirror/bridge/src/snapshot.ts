import { randomBytes } from "node:crypto";
import { mkdir, readFile, rename, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { isReadOnly, type BridgeConfig } from "./config";
import { hashFile, sameScan, scanTree, type ScannedFile } from "./scan";

export interface SnapshotFile extends ScannedFile {
  id: string;
  sha256: string;
}

export interface Snapshot {
  snapshotId: string;
  generatedAt: string;
  files: SnapshotFile[];
  excluded: Record<string, number>;
}

export class IncompleteError extends Error {
  constructor(readonly problems: string[]) {
    super(`incomplete snapshot: ${problems.slice(0, 3).join("; ")}`);
  }
}

const cacheKey = (f: ScannedFile) => `${f.path}\u0000${f.size}\u0000${f.mtimeMs}`;

/** SHA-256 cache keyed by (path, size, mtime), stored outside the root (DESIGN D-3). */
export class HashCache {
  private map = new Map<string, string>();
  private dirty = false;
  constructor(private readonly file: string) {}

  async load(): Promise<void> {
    try {
      const raw = JSON.parse(await readFile(this.file, "utf8")) as Record<string, string>;
      this.map = new Map(Object.entries(raw));
    } catch {
      this.map = new Map();
    }
  }

  get(f: ScannedFile): string | undefined {
    return this.map.get(cacheKey(f));
  }

  set(f: ScannedFile, sha: string): void {
    this.map.set(cacheKey(f), sha);
    this.dirty = true;
  }

  /** Keep only entries for the current tree, then persist atomically. */
  async retainAndSave(files: ScannedFile[]): Promise<void> {
    const keep = new Set(files.map(cacheKey));
    for (const k of this.map.keys()) {
      if (!keep.has(k)) {
        this.map.delete(k);
        this.dirty = true;
      }
    }
    if (!this.dirty) return;
    const tmp = `${this.file}.${process.pid}.tmp`;
    await writeFile(tmp, JSON.stringify(Object.fromEntries(this.map)), { mode: 0o600 });
    await rename(tmp, this.file);
    this.dirty = false;
  }
}

export interface Snapshotter {
  build(): Promise<Snapshot>;
  lookup(id: string): SnapshotFile | undefined;
}

export async function createSnapshotter(
  cfg: BridgeConfig,
  root: string,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<Snapshotter> {
  await mkdir(cfg.stateDir, { recursive: true, mode: 0o700 });
  const cache = new HashCache(join(cfg.stateDir, "hash-cache.json"));
  await cache.load();
  const snapshots: Snapshot[] = [];
  const byId = new Map<string, SnapshotFile>();
  let inflight: Promise<Snapshot> | null = null;

  async function checkMarker(): Promise<void> {
    if (cfg.requireReadOnlyRoot && !isReadOnly(root)) {
      throw new IncompleteError(["root is writable by the bridge; serve it from the read-only bind mount (scripts/install-ro-mount.sh)"]);
    }
    if (!cfg.requireMarker) return;
    try {
      await stat(join(root, cfg.requireMarker));
    } catch {
      throw new IncompleteError([`marker ${cfg.requireMarker} not found under root (is Drive for desktop running and mounted?)`]);
    }
  }

  async function buildOnce(): Promise<Snapshot> {
    await checkMarker();
    const first = await scanTree(root);
    if (first.problems.length) throw new IncompleteError(first.problems);
    await sleep(cfg.stabilityDelayMs);
    const second = await scanTree(root);
    if (second.problems.length) throw new IncompleteError(second.problems);
    if (!sameScan(first.files, second.files)) throw new IncompleteError(["tree changed between stability scans; retry later"]);

    const snapshotId = randomBytes(12).toString("base64url");
    const files: SnapshotFile[] = [];
    const problems: string[] = [];
    for (const f of second.files) {
      let sha = cache.get(f);
      try {
        if (!sha) {
          const h = await hashFile(root, f.path);
          sha = h.sha256;
          if (h.size !== f.size || h.mtimeMs !== f.mtimeMs) {
            problems.push(`changed while hashing ${JSON.stringify(f.path)}`);
            continue;
          }
          cache.set(f, sha);
        }
      } catch (e) {
        problems.push(`unreadable ${JSON.stringify(f.path)}: ${(e as NodeJS.ErrnoException).code ?? e}`);
        continue;
      }
      files.push({ ...f, sha256: sha, id: randomBytes(16).toString("base64url") });
    }
    await cache.retainAndSave(second.files);
    if (problems.length) throw new IncompleteError(problems);

    const snap: Snapshot = { snapshotId, generatedAt: new Date().toISOString(), files, excluded: second.excluded };
    snapshots.push(snap);
    for (const f of files) byId.set(f.id, f);
    while (snapshots.length > cfg.maxSnapshots) {
      for (const f of snapshots.shift()!.files) byId.delete(f.id);
    }
    return snap;
  }

  return {
    build() {
      // Concurrent manifest requests share one scan.
      inflight ??= buildOnce().finally(() => {
        inflight = null;
      });
      return inflight;
    },
    lookup: (id) => byId.get(id),
  };
}
