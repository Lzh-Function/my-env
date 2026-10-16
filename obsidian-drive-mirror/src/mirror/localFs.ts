// Vault-relative filesystem seam. The Obsidian implementation lives in ../obsidianFs.ts; tests use an in-memory one.

export interface LocalStat {
  type: "file" | "folder";
  size: number;
}

export interface LocalFs {
  /** Direct children of `dir` ("" = vault root), as vault-relative paths. */
  list(dir: string): Promise<{ files: string[]; folders: string[] }>;
  stat(path: string): Promise<LocalStat | null>;
  readBinary(path: string): Promise<ArrayBuffer>;
  /** Create or overwrite a file. Parent folders must exist. */
  writeBinary(path: string, data: ArrayBuffer): Promise<void>;
  appendBinary(path: string, data: ArrayBuffer): Promise<void>;
  /** Remove a file. */
  remove(path: string): Promise<void>;
  /** Remove an empty folder. */
  rmdir(path: string): Promise<void>;
  mkdir(path: string): Promise<void>;
  /** Rename a file; the destination must not exist. */
  rename(from: string, to: string): Promise<void>;
}

export async function mkdirp(fs: LocalFs, dir: string): Promise<void> {
  if (dir === "") return;
  const segs = dir.split("/");
  for (let i = 1; i <= segs.length; i++) {
    const p = segs.slice(0, i).join("/");
    const st = await fs.stat(p);
    if (!st) await fs.mkdir(p);
    else if (st.type !== "folder") throw new Error(`Cannot create folder over file: ${p}`);
  }
}
