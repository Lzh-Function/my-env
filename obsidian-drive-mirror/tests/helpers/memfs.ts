import type { LocalFs, LocalStat } from "../../src/mirror/localFs";
import type { MirrorState, StateStore } from "../../src/mirror/state";

/** In-memory LocalFs. `caseInsensitive` mimics Windows / default APFS name lookup. */
export class MemFs implements LocalFs {
  readonly files = new Map<string, Uint8Array>();
  readonly folders = new Set<string>();
  failWrite: (path: string) => boolean = () => false;

  constructor(private readonly caseInsensitive = false) {}

  private find(path: string): { kind: "file" | "folder"; actual: string } | null {
    if (this.files.has(path)) return { kind: "file", actual: path };
    if (this.folders.has(path)) return { kind: "folder", actual: path };
    if (!this.caseInsensitive) return null;
    const k = path.normalize("NFC").toLowerCase();
    for (const p of this.files.keys()) if (p.normalize("NFC").toLowerCase() === k) return { kind: "file", actual: p };
    for (const p of this.folders) if (p.normalize("NFC").toLowerCase() === k) return { kind: "folder", actual: p };
    return null;
  }

  private parentOk(path: string): void {
    const i = path.lastIndexOf("/");
    if (i > 0 && this.find(path.slice(0, i))?.kind !== "folder") throw new Error(`ENOENT parent of ${path}`);
  }

  put(path: string, content: string | Uint8Array): void {
    const segs = path.split("/");
    for (let i = 1; i < segs.length; i++) this.folders.add(segs.slice(0, i).join("/"));
    this.files.set(path, typeof content === "string" ? new TextEncoder().encode(content) : content);
  }

  text(path: string): string | undefined {
    const d = this.files.get(path);
    return d && new TextDecoder().decode(d);
  }

  async list(dir: string) {
    const prefix = dir === "" ? "" : dir + "/";
    const direct = (p: string) => p.startsWith(prefix) && !p.slice(prefix.length).includes("/") && p !== dir;
    return { files: [...this.files.keys()].filter(direct), folders: [...this.folders].filter(direct) };
  }

  async stat(path: string): Promise<LocalStat | null> {
    const f = this.find(path);
    if (!f) return null;
    return f.kind === "file" ? { type: "file", size: this.files.get(f.actual)!.byteLength } : { type: "folder", size: 0 };
  }

  async readBinary(path: string): Promise<ArrayBuffer> {
    const f = this.find(path);
    if (f?.kind !== "file") throw new Error(`ENOENT ${path}`);
    return this.files.get(f.actual)!.slice().buffer as ArrayBuffer;
  }

  async writeBinary(path: string, data: ArrayBuffer): Promise<void> {
    if (this.failWrite(path)) throw new Error(`EIO ${path}`);
    this.parentOk(path);
    const f = this.find(path);
    if (f?.kind === "folder") throw new Error(`EISDIR ${path}`);
    this.files.set(f?.actual ?? path, new Uint8Array(data.slice(0)));
  }

  async appendBinary(path: string, data: ArrayBuffer): Promise<void> {
    const f = this.find(path);
    if (f?.kind !== "file") throw new Error(`ENOENT ${path}`);
    const old = this.files.get(f.actual)!;
    const merged = new Uint8Array(old.byteLength + data.byteLength);
    merged.set(old);
    merged.set(new Uint8Array(data), old.byteLength);
    this.files.set(f.actual, merged);
  }

  async remove(path: string): Promise<void> {
    const f = this.find(path);
    if (f?.kind !== "file") throw new Error(`ENOENT ${path}`);
    this.files.delete(f.actual);
  }

  async rmdir(path: string): Promise<void> {
    const f = this.find(path);
    if (f?.kind !== "folder") throw new Error(`ENOENT ${path}`);
    const { files, folders } = await this.list(f.actual);
    if (files.length || folders.length) throw new Error(`ENOTEMPTY ${path}`);
    this.folders.delete(f.actual);
  }

  async mkdir(path: string): Promise<void> {
    if (this.find(path)) throw new Error(`EEXIST ${path}`);
    this.parentOk(path);
    this.folders.add(path);
  }

  async rename(from: string, to: string): Promise<void> {
    if (this.failWrite(to)) throw new Error(`EIO ${to}`);
    const f = this.find(from);
    if (f?.kind !== "file") throw new Error(`ENOENT ${from}`);
    const dest = this.find(to);
    if (dest && dest.actual !== f.actual) throw new Error(`EEXIST ${to}`);
    this.parentOk(to);
    const data = this.files.get(f.actual)!;
    this.files.delete(f.actual);
    this.files.set(to, data);
  }
}

export class MemStore implements StateStore {
  state: MirrorState | null = null;
  async load() {
    return this.state ? structuredClone(this.state) : null;
  }
  async save(s: MirrorState) {
    this.state = structuredClone(s);
  }
}
