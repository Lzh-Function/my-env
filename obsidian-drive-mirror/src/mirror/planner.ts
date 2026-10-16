import { collisionKey } from "../security/paths";
import type { RemoteEntry, RemoteManifest } from "../provider/types";
import type { LocalIndex } from "./scanner";
import type { MirrorState } from "./state";

export interface Upsert {
  entry: RemoteEntry;
  kind: "create" | "replace";
  /** Local content differs from what we last wrote (a local edit being discarded). */
  localEdit: boolean;
  /** A local file with a case/normalization variant of this path that must be removed before placing. */
  fromPath?: string;
}

export interface Deletion {
  path: string;
  reason: "remote_deleted" | "local_only";
}

/** Soft gates: allowed only after explicit approval in the preview. */
export type Confirmation = "mass_delete" | "remote_empty" | "first_sync_nonempty";
/** Hard gates: syncing refuses until settings change. */
export type Block = "root_changed" | "first_sync_nonempty";

export interface PlanSettings {
  maxFileSizeBytes: number;
  deleteThresholdCount: number;
  deleteThresholdRatio: number;
  allowNonEmptyInit: boolean;
}

export interface Plan {
  manifest: RemoteManifest;
  upserts: Upsert[];
  deletes: Deletion[];
  unchanged: RemoteEntry[];
  skippedOversize: RemoteEntry[];
  localFileCount: number;
  excludedLocal: number;
  hashedLocalBytes: number;
  confirmations: Confirmation[];
  blocks: Block[];
  warnings: string[];
}

export function planMirror(manifest: RemoteManifest, local: LocalIndex, state: MirrorState, settings: PlanSettings): Plan {
  const remoteByPath = new Map(manifest.entries.map((e) => [e.path, e]));
  const remoteByKey = new Map(manifest.entries.map((e) => [collisionKey(e.path), e]));

  const upserts: Upsert[] = [];
  const unchanged: RemoteEntry[] = [];
  const skippedOversize: RemoteEntry[] = [];
  const deletes: Deletion[] = [];
  const warnings: string[] = [];
  const variantFor = new Map<string, string>(); // remote path -> local variant path

  for (const path of local.files.keys()) {
    if (remoteByPath.has(path)) continue;
    const variantOf = remoteByKey.get(collisionKey(path));
    if (variantOf && !local.files.has(variantOf.path) && !variantFor.has(variantOf.path)) {
      variantFor.set(variantOf.path, path);
      continue;
    }
    deletes.push({ path, reason: state.records[path] ? "remote_deleted" : "local_only" });
  }

  for (const entry of manifest.entries) {
    const localFile = local.files.get(entry.path);
    if (entry.size > settings.maxFileSizeBytes) {
      skippedOversize.push(entry);
      if (!localFile || localFile.sha256 !== entry.sha256) warnings.push(`Oversize file not mirrored: ${entry.path}`);
      continue;
    }
    const record = state.records[entry.path];
    if (localFile) {
      if (localFile.sha256 === entry.sha256) {
        unchanged.push(entry);
      } else {
        const localEdit = !record || record.contentSha256 !== localFile.sha256;
        upserts.push({ entry, kind: "replace", localEdit });
      }
      continue;
    }
    const fromPath = variantFor.get(entry.path);
    upserts.push(fromPath ? { entry, kind: "replace", localEdit: true, fromPath } : { entry, kind: "create", localEdit: false });
  }
  // A variant whose remote is oversize is still a local-only name: delete it.
  for (const entry of skippedOversize) {
    const v = variantFor.get(entry.path);
    if (v) deletes.push({ path: v, reason: "local_only" });
  }

  const confirmations: Confirmation[] = [];
  const blocks: Block[] = [];
  const localCount = local.files.size;
  if (state.rootIdentity && state.rootIdentity.rootId !== manifest.rootIdentity.rootId) blocks.push("root_changed");
  if (!state.rootIdentity && localCount > 0) {
    if (settings.allowNonEmptyInit) confirmations.push("first_sync_nonempty");
    else blocks.push("first_sync_nonempty");
  }
  if (manifest.entries.length === 0 && localCount > 0) confirmations.push("remote_empty");
  if (deletes.length >= settings.deleteThresholdCount && deletes.length >= localCount * settings.deleteThresholdRatio) {
    confirmations.push("mass_delete");
  }

  return {
    manifest,
    upserts,
    deletes,
    unchanged,
    skippedOversize,
    localFileCount: localCount,
    excludedLocal: local.excluded,
    hashedLocalBytes: local.hashedBytes,
    confirmations,
    blocks,
    warnings,
  };
}
