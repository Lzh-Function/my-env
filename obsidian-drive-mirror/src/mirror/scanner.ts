import { isProtectedPath } from "../security/paths";
import { sha256Hex } from "../util/hash";
import { throwIfAborted } from "../util/retry";
import type { LocalFs } from "./localFs";

export interface LocalFile {
  size: number;
  sha256: string;
}

export interface LocalIndex {
  files: Map<string, LocalFile>;
  /** Managed (non-protected) folders, parents before children. */
  folders: string[];
  /** Protected/hidden entries found at the top of skipped subtrees (not descended into). */
  excluded: number;
  hashedBytes: number;
}

/**
 * Enumerate every managed local file and hash its full content (strict mode, DESIGN §7.2).
 * Protected paths (configDir, hidden files/folders) are skipped without descending.
 */
export async function scanLocal(
  fs: LocalFs,
  configDir: string,
  opts: { signal?: AbortSignal; onProgress?: (files: number, bytes: number) => void } = {},
): Promise<LocalIndex> {
  const index: LocalIndex = { files: new Map(), folders: [], excluded: 0, hashedBytes: 0 };
  const queue: string[] = [""];
  while (queue.length > 0) {
    const dir = queue.shift()!;
    const { files, folders } = await fs.list(dir);
    for (const folder of folders) {
      if (isProtectedPath(folder, configDir)) {
        index.excluded++;
        continue;
      }
      index.folders.push(folder);
      queue.push(folder);
    }
    for (const file of files) {
      throwIfAborted(opts.signal);
      if (isProtectedPath(file, configDir)) {
        index.excluded++;
        continue;
      }
      const data = await fs.readBinary(file);
      index.files.set(file, { size: data.byteLength, sha256: sha256Hex(data) });
      index.hashedBytes += data.byteLength;
      opts.onProgress?.(index.files.size, index.hashedBytes);
    }
  }
  return index;
}
