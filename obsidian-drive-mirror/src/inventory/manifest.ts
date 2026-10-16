import { collisionKey, isHiddenPath, parentDirs, validateRelPath } from "../security/paths";
import type { RemoteEntry, RemoteManifest } from "../provider/types";

export class ManifestError extends Error {
  constructor(readonly problems: string[]) {
    super(`Invalid remote manifest: ${problems.slice(0, 5).join("; ")}${problems.length > 5 ? ` (+${problems.length - 5} more)` : ""}`);
    this.name = "ManifestError";
  }
}

const HEX64 = /^[0-9a-f]{64}$/;

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Validate an untrusted manifest. Anything short of a complete, internally consistent,
 * collision-free tree is rejected so that the prune phase can never act on it.
 */
export function validateManifest(raw: unknown): RemoteManifest {
  const problems: string[] = [];
  if (!isRecord(raw)) throw new ManifestError(["not an object"]);
  if (raw.schemaVersion !== 1) problems.push(`unsupported schemaVersion ${String(raw.schemaVersion)}`);
  if (raw.complete !== true) problems.push("snapshot is not complete");
  if (typeof raw.snapshotId !== "string" || raw.snapshotId.length === 0) problems.push("missing snapshotId");
  if (typeof raw.generatedAt !== "string") problems.push("missing generatedAt");
  const root = raw.rootIdentity;
  if (!isRecord(root) || typeof root.rootId !== "string" || root.rootId.length === 0 || typeof root.name !== "string") {
    problems.push("missing rootIdentity");
  }
  if (!Array.isArray(raw.entries)) problems.push("entries is not an array");
  if (problems.length > 0) throw new ManifestError(problems);

  const entries: RemoteEntry[] = [];
  const ids = new Set<string>();
  const keys = new Map<string, string>();
  for (const [i, e] of (raw.entries as unknown[]).entries()) {
    if (!isRecord(e)) {
      problems.push(`entry ${i}: not an object`);
      continue;
    }
    const { id, path, size, modifiedTime, sha256 } = e;
    if (typeof id !== "string" || id.length === 0) problems.push(`entry ${i}: missing id`);
    if (typeof path !== "string") {
      problems.push(`entry ${i}: missing path`);
      continue;
    }
    const pathProblem = validateRelPath(path);
    if (pathProblem) problems.push(`${JSON.stringify(path)}: ${pathProblem}`);
    if (isHiddenPath(path)) problems.push(`${JSON.stringify(path)}: hidden path must not be listed`);
    if (typeof size !== "number" || !Number.isSafeInteger(size) || size < 0) problems.push(`${JSON.stringify(path)}: bad size`);
    if (typeof sha256 !== "string" || !HEX64.test(sha256)) problems.push(`${JSON.stringify(path)}: bad sha256`);
    if (modifiedTime !== null && modifiedTime !== undefined && typeof modifiedTime !== "string") {
      problems.push(`${JSON.stringify(path)}: bad modifiedTime`);
    }
    if (typeof id === "string") {
      if (ids.has(id)) problems.push(`duplicate id ${id}`);
      ids.add(id);
    }
    const key = collisionKey(path);
    const prev = keys.get(key);
    if (prev !== undefined) problems.push(`${JSON.stringify(path)} collides with ${JSON.stringify(prev)}`);
    keys.set(key, path);
    entries.push({
      id: id as string,
      path,
      size: size as number,
      modifiedTime: (modifiedTime as string | null | undefined) ?? null,
      sha256: sha256 as string,
    });
  }

  // A path cannot be both a file and a directory.
  for (const e of entries) {
    for (const dir of parentDirs(e.path)) {
      const clash = keys.get(collisionKey(dir));
      if (clash !== undefined) problems.push(`${JSON.stringify(clash)} is a file but also a directory of ${JSON.stringify(e.path)}`);
    }
  }

  if (problems.length > 0) throw new ManifestError(problems);

  const excluded: Record<string, number> = {};
  if (isRecord(raw.excluded)) {
    for (const [k, v] of Object.entries(raw.excluded)) if (typeof v === "number") excluded[k] = v;
  }

  return {
    schemaVersion: 1,
    snapshotId: raw.snapshotId as string,
    complete: true,
    generatedAt: raw.generatedAt as string,
    rootIdentity: { rootId: (root as Record<string, string>).rootId!, name: (root as Record<string, string>).name! },
    entries,
    excluded,
  };
}
