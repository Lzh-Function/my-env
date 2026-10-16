import { normalizePath, requestUrl, type DataAdapter } from "obsidian";
import type { LocalFs, LocalStat } from "./mirror/localFs";
import type { MirrorState, StateStore } from "./mirror/state";
import type { HttpFn } from "./provider/bridge";

const strip = (p: string) => p.replace(/^\/+/, "");

/**
 * LocalFs over Obsidian's DataAdapter (works on desktop and iOS; no Node APIs).
 * All paths are vault-relative. The engine guarantees protected paths are only touched under the plugin's own dir.
 */
export class AdapterFs implements LocalFs {
  constructor(private readonly adapter: DataAdapter) {}

  async list(dir: string) {
    const r = await this.adapter.list(dir === "" ? "/" : normalizePath(dir));
    return { files: r.files.map(strip), folders: r.folders.map(strip) };
  }

  async stat(path: string): Promise<LocalStat | null> {
    const s = await this.adapter.stat(normalizePath(path));
    if (!s) return null;
    return { type: s.type, size: s.size };
  }

  readBinary(path: string) {
    return this.adapter.readBinary(normalizePath(path));
  }

  writeBinary(path: string, data: ArrayBuffer) {
    return this.adapter.writeBinary(normalizePath(path), data);
  }

  appendBinary(path: string, data: ArrayBuffer) {
    return this.adapter.appendBinary(normalizePath(path), data);
  }

  remove(path: string) {
    return this.adapter.remove(normalizePath(path));
  }

  rmdir(path: string) {
    return this.adapter.rmdir(normalizePath(path), false);
  }

  mkdir(path: string) {
    return this.adapter.mkdir(normalizePath(path));
  }

  async rename(from: string, to: string) {
    if (await this.adapter.exists(normalizePath(to), true)) {
      // Allow case-only renames on case-insensitive filesystems; otherwise refuse to clobber.
      if (from.toLowerCase() !== to.toLowerCase()) throw new Error(`Destination exists: ${to}`);
    }
    await this.adapter.rename(normalizePath(from), normalizePath(to));
  }
}

export class AdapterStateStore implements StateStore {
  constructor(
    private readonly adapter: DataAdapter,
    private readonly path: string,
  ) {}

  async load(): Promise<MirrorState | null> {
    if (!(await this.adapter.exists(this.path))) return null;
    return JSON.parse(await this.adapter.read(this.path)) as MirrorState;
  }

  async save(state: MirrorState): Promise<void> {
    await this.adapter.write(this.path, JSON.stringify(state));
  }
}

/** Obsidian's requestUrl: bypasses CORS and works on iOS. Never throws on HTTP status. */
export const obsidianHttp: HttpFn = async (req) => {
  const res = await requestUrl({ url: req.url, method: req.method, headers: req.headers, throw: false });
  const headers: Record<string, string> = {};
  for (const [k, v] of Object.entries(res.headers ?? {})) headers[k.toLowerCase()] = v;
  return { status: res.status, headers, body: res.arrayBuffer };
};
