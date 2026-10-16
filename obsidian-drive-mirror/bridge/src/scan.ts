import { lstat, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { collisionKey, validateSegment } from "../../src/security/paths";
import { openInsideRoot } from "./safeOpen";

export interface ScannedFile {
  path: string; // POSIX, relative to root
  size: number;
  mtimeMs: number;
}

export interface ScanResult {
  files: ScannedFile[];
  excluded: Record<string, number>;
  /** Anything here makes the snapshot incomplete. */
  problems: string[];
}

const GOOGLE_NATIVE = /\.(gdoc|gsheet|gslides|gdraw|gform|gmap|gsite|gjam|gscript|glink|gtable)$/i;
// Office/editor temp & Drive partial files indicate an unsettled tree (DESIGN D-4).
const TEMP_FILE = /^~\$|\.tmp$|\.crdownload$|\.partial$/i;

function bump(m: Record<string, number>, k: string): void {
  m[k] = (m[k] ?? 0) + 1;
}

/** Walk root read-only. Never follows symlinks; hidden entries are skipped without descending. */
export async function scanTree(root: string): Promise<ScanResult> {
  const result: ScanResult = { files: [], excluded: {}, problems: [] };
  const keys = new Map<string, string>();
  const queue: string[] = [""];
  while (queue.length > 0) {
    const rel = queue.shift()!;
    let names: string[];
    try {
      names = await readdir(join(root, rel));
    } catch (e) {
      result.problems.push(`unreadable directory ${JSON.stringify(rel || "/")}: ${(e as NodeJS.ErrnoException).code ?? e}`);
      continue;
    }
    for (const name of names.sort()) {
      const childRel = rel ? `${rel}/${name}` : name;
      if (name.startsWith(".")) {
        bump(result.excluded, "hidden");
        continue;
      }
      let st;
      try {
        st = await lstat(join(root, childRel));
      } catch (e) {
        result.problems.push(`cannot stat ${JSON.stringify(childRel)}: ${(e as NodeJS.ErrnoException).code ?? e}`);
        continue;
      }
      if (st.isSymbolicLink()) {
        bump(result.excluded, "symlink");
        continue;
      }
      if (!st.isFile() && !st.isDirectory()) {
        bump(result.excluded, "special");
        continue;
      }
      const problem = validateSegment(name);
      if (problem === "forbidden_char") {
        // e.g. "remote-capture:xxxx" surfaced by Drive for desktop; excluded and counted (DESIGN D-14).
        bump(result.excluded, "unsupported_name");
        continue;
      }
      if (problem) {
        result.problems.push(`invalid name ${JSON.stringify(childRel)}: ${problem}`);
        continue;
      }
      const key = collisionKey(childRel);
      const clash = keys.get(key);
      if (clash !== undefined) {
        result.problems.push(`name collision ${JSON.stringify(childRel)} vs ${JSON.stringify(clash)}`);
        continue;
      }
      keys.set(key, childRel);
      if (st.isDirectory()) {
        queue.push(childRel);
        continue;
      }
      if (GOOGLE_NATIVE.test(name)) {
        bump(result.excluded, "google_native");
        continue;
      }
      if (/\.lnk$/i.test(name)) {
        bump(result.excluded, "shortcut");
        continue;
      }
      if (TEMP_FILE.test(name)) {
        result.problems.push(`temporary file present ${JSON.stringify(childRel)}`);
        continue;
      }
      result.files.push({ path: childRel, size: st.size, mtimeMs: st.mtimeMs });
    }
  }
  result.files.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
  return result;
}

export function sameScan(a: ScannedFile[], b: ScannedFile[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((f, i) => {
    const g = b[i]!;
    return f.path === g.path && f.size === g.size && f.mtimeMs === g.mtimeMs;
  });
}

/** Hash through a verified descriptor; size/mtime come from that same descriptor after reading. */
export async function hashFile(root: string, rel: string): Promise<{ sha256: string; size: number; mtimeMs: number }> {
  const { fh } = await openInsideRoot(root, rel);
  try {
    const h = createHash("sha256");
    for await (const chunk of fh.createReadStream({ autoClose: false })) h.update(chunk as Buffer);
    const after = await fh.stat();
    return { sha256: h.digest("hex"), size: after.size, mtimeMs: after.mtimeMs };
  } finally {
    await fh.close();
  }
}
