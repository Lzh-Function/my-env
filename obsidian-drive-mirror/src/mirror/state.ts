import type { RootIdentity } from "../provider/types";

export interface LocalRecord {
  remoteId: string;
  path: string;
  /** Remote sha256 at the time of the last successful placement. */
  remoteFingerprint: string;
  /** sha256 of the bytes written locally. */
  contentSha256: string;
  size: number;
}

export type SyncStatus = "SUCCESS" | "PARTIAL" | "FAILED" | "CANCELLED" | "BLOCKED" | "DRY_RUN";

export interface SyncFailure {
  path: string | null;
  code: string;
  message: string;
}

/** Content-free summary of a run (DESIGN §9: no note bodies or credentials). */
export interface SyncReport {
  status: SyncStatus;
  startedAt: string;
  finishedAt: string;
  snapshotId: string | null;
  counts: {
    remote: number;
    local: number;
    create: number;
    replace: number;
    localEdits: number;
    delete: number;
    unchanged: number;
    skippedOversize: number;
    excludedRemote: number;
    excludedLocal: number;
  };
  applied: { created: number; replaced: number; deleted: number; foldersRemoved: number };
  bytesDownloaded: number;
  hashedLocalBytes: number;
  failures: SyncFailure[];
  warnings: string[];
}

export interface MirrorState {
  schemaVersion: 1;
  /** Pinned on the first apply (DESIGN D-8). A different root blocks syncing until re-pinned. */
  rootIdentity: RootIdentity | null;
  vaultIdentity: string;
  generation: number;
  lastCompleteSyncAt: string | null;
  records: Record<string, LocalRecord>;
  history: SyncReport[];
}

export const HISTORY_LIMIT = 20;

export function emptyState(vaultIdentity: string): MirrorState {
  return {
    schemaVersion: 1,
    rootIdentity: null,
    vaultIdentity,
    generation: 0,
    lastCompleteSyncAt: null,
    records: {},
    history: [],
  };
}

export interface StateStore {
  load(): Promise<MirrorState | null>;
  save(state: MirrorState): Promise<void>;
}
