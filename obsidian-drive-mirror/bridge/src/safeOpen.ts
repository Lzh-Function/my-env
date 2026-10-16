import { constants, type Stats } from "node:fs";
import { open, readlink, type FileHandle } from "node:fs/promises";
import { join } from "node:path";

export class UnsafePathError extends Error {}

/**
 * Open root/rel for reading without a check-then-open race:
 *  - O_NOFOLLOW refuses a symlink in the final component,
 *  - O_NONBLOCK keeps a FIFO swapped in after listing from hanging the open,
 *  - the kernel's view of the opened file (/proc/self/fd) must equal the expected path,
 *    which rejects a symlinked/junctioned parent swapped in after the scan,
 *  - fstat on the descriptor (not the path) must be a regular file.
 * The caller reads from the returned handle only, so later path swaps cannot redirect it.
 */
export async function openInsideRoot(root: string, rel: string): Promise<{ fh: FileHandle; stats: Stats }> {
  const expected = join(root, rel);
  const fh = await open(expected, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const actual = await readlink(`/proc/self/fd/${fh.fd}`);
    if (actual !== expected) throw new UnsafePathError("opened file is not at the expected path");
    const stats = await fh.stat();
    if (!stats.isFile()) throw new UnsafePathError("not a regular file");
    return { fh, stats };
  } catch (e) {
    await fh.close();
    throw e;
  }
}
