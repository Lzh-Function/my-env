import { collisionKey, isProtectedPath, parentDirs } from "../security/paths";
import { ProviderError, type RemoteEntry, type RemoteReadProvider } from "../provider/types";
import { ManifestError } from "../inventory/manifest";
import { createSha256, sha256Hex } from "../util/hash";
import { throwIfAborted } from "../util/retry";
import { mkdirp, type LocalFs } from "./localFs";
import { planMirror, type Plan, type PlanSettings, type Upsert } from "./planner";
import { scanLocal } from "./scanner";
import {
  emptyState,
  HISTORY_LIMIT,
  type LocalRecord,
  type MirrorState,
  type StateStore,
  type SyncFailure,
  type SyncReport,
  type SyncStatus,
} from "./state";

export type SyncPhase =
  | "IDLE" | "AUTH" | "SCAN_REMOTE" | "SCAN_LOCAL" | "PLAN" | "STAGE_DOWNLOADS"
  | "VERIFY" | "APPLY_UPSERTS" | "PRUNE" | "COMMIT" | "DONE" | "FAILED";

export interface EngineSettings extends PlanSettings {
  chunkSizeBytes: number;
  concurrency: number;
  /** Files up to this size are read back and re-hashed after placement. */
  readbackVerifyLimitBytes: number;
}

export interface Progress {
  phase: SyncPhase;
  done: number;
  total: number;
}

export interface EngineDeps {
  fs: LocalFs;
  provider: RemoteReadProvider;
  store: StateStore;
  configDir: string;
  /** Plugin-owned directory under configDir (staging lives here). */
  internalDir: string;
  settings: EngineSettings;
  now?: () => Date;
  newId?: () => string;
  onProgress?: (p: Progress) => void;
}

export interface RunOptions {
  dryRun?: boolean;
  signal?: AbortSignal;
  /**
   * Called with the plan before anything is written. Return true to apply.
   * Required whenever the plan has confirmations; without it such plans are not applied.
   */
  approve?: (plan: Plan) => Promise<boolean>;
}

export interface RunResult {
  report: SyncReport;
  plan: Plan | null;
}

export class MirrorEngine {
  private running = false;

  constructor(private readonly deps: EngineDeps) {}

  get isRunning(): boolean {
    return this.running;
  }

  async run(opts: RunOptions = {}): Promise<RunResult> {
    if (this.running) throw new Error("A sync is already running");
    this.running = true;
    try {
      return await this.runLocked(opts);
    } finally {
      this.running = false;
    }
  }

  private progress(phase: SyncPhase, done = 0, total = 0): void {
    this.deps.onProgress?.({ phase, done, total });
  }

  private async runLocked(opts: RunOptions): Promise<RunResult> {
    const { fs, provider, store, configDir, settings } = this.deps;
    const now = this.deps.now ?? (() => new Date());
    const startedAt = now().toISOString();
    const state: MirrorState = (await store.load()) ?? emptyState((this.deps.newId ?? randomId)());
    const failures: SyncFailure[] = [];
    let plan: Plan | null = null;

    const finish = async (status: SyncStatus, extra: Partial<Pick<SyncReport, "applied" | "bytesDownloaded">> = {}): Promise<RunResult> => {
      const report = buildReport(status, startedAt, now().toISOString(), plan, failures, extra);
      if (status !== "DRY_RUN") {
        state.history = [report, ...state.history].slice(0, HISTORY_LIMIT);
        await store.save(state);
      }
      this.progress(status === "SUCCESS" || status === "PARTIAL" || status === "DRY_RUN" ? "DONE" : "FAILED");
      return { report, plan };
    };

    // SCAN_REMOTE + SCAN_LOCAL + PLAN
    try {
      this.progress("SCAN_REMOTE");
      const manifest = await provider.listCompleteTree(opts.signal);
      this.progress("SCAN_LOCAL");
      const local = await scanLocal(fs, configDir, {
        signal: opts.signal,
        onProgress: (n) => this.progress("SCAN_LOCAL", n, 0),
      });
      this.progress("PLAN");
      plan = planMirror(manifest, local, state, settings);
    } catch (e) {
      if (isAbort(e)) return finish("CANCELLED");
      failures.push(failureFrom(null, e));
      return finish("FAILED");
    }

    if (opts.dryRun) return finish("DRY_RUN");
    if (plan.blocks.length > 0) {
      for (const b of plan.blocks) failures.push({ path: null, code: b, message: blockMessage(b) });
      return finish("BLOCKED");
    }
    if (opts.approve) {
      if (!(await opts.approve(plan))) return finish("CANCELLED");
    } else if (plan.confirmations.length > 0) {
      for (const c of plan.confirmations) failures.push({ path: null, code: c, message: `Needs confirmation: ${c}` });
      return finish("BLOCKED");
    }
    if (opts.signal?.aborted) return finish("CANCELLED");

    // Pin the root before the first write so that a half-finished first sync is not mistaken for a foreign vault.
    if (!state.rootIdentity) {
      state.rootIdentity = plan.manifest.rootIdentity;
      await store.save(state);
    }

    const applied = { created: 0, replaced: 0, deleted: 0, foldersRemoved: 0 };
    const staging = `${this.deps.internalDir}/staging`;
    await this.resetStaging(staging);

    const deleteSet = new Set(plan.deletes.map((d) => d.path));
    const removed = new Set<string>();
    const newRecords: Record<string, LocalRecord> = {};
    let bytesDownloaded = 0;
    let fatal: unknown = null;
    let placing: Promise<void> = Promise.resolve(); // placement is serialized; downloads run concurrently
    let done = 0;

    const work = plan.upserts.map((u, i) => async () => {
      if (fatal) return;
      try {
        throwIfAborted(opts.signal);
        const stagePath = `${staging}/${i}.part`;
        bytesDownloaded += await this.download(u.entry, stagePath, opts.signal);
        const place = placing.then(() => this.place(u, stagePath, `${staging}/${i}.bak`, deleteSet, removed));
        placing = place.catch(() => undefined);
        await place;
        newRecords[u.entry.path] = record(u.entry);
        if (u.kind === "create") applied.created++;
        else applied.replaced++;
      } catch (e) {
        if (isAbort(e) || (e instanceof ProviderError && (e.code === "auth" || e.code === "conflict"))) fatal ??= e;
        else failures.push(failureFrom(u.entry.path, e));
      } finally {
        this.progress("APPLY_UPSERTS", ++done, plan!.upserts.length);
      }
    });
    await pool(work, Math.max(1, settings.concurrency));

    if (fatal) {
      if (isAbort(fatal)) return this.finishPartialRun(state, newRecords, staging, () => finish("CANCELLED", { applied, bytesDownloaded }));
      failures.push(failureFrom(null, fatal));
    }
    if (failures.length > 0 || opts.signal?.aborted) {
      // No prune: a failed or cancelled run must never delete (DESIGN §7.5).
      const status: SyncStatus = opts.signal?.aborted && failures.length === 0 ? "CANCELLED" : "FAILED";
      return this.finishPartialRun(state, newRecords, staging, () => finish(status, { applied, bytesDownloaded }));
    }

    // PRUNE
    this.progress("PRUNE", 0, plan.deletes.length);
    for (const d of plan.deletes) {
      if (removed.has(d.path)) continue;
      try {
        const st = await fs.stat(d.path);
        if (st?.type === "file") await fs.remove(d.path);
        removed.add(d.path);
      } catch (e) {
        failures.push(failureFrom(d.path, e));
      }
    }
    applied.deleted = removed.size;
    applied.foldersRemoved = await this.removeEmptyFolders(plan, failures);

    // COMMIT
    this.progress("COMMIT");
    const records: Record<string, LocalRecord> = {};
    for (const e of plan.unchanged) records[e.path] = record(e);
    for (const e of plan.skippedOversize) {
      const old = state.records[e.path];
      if (old) records[e.path] = old;
    }
    Object.assign(records, newRecords);
    state.records = records;
    state.generation++;
    const status: SyncStatus = failures.length > 0 ? "FAILED" : plan.skippedOversize.length > 0 ? "PARTIAL" : "SUCCESS";
    if (status === "SUCCESS") state.lastCompleteSyncAt = now().toISOString();
    await this.resetStaging(staging);
    return finish(status, { applied, bytesDownloaded });
  }

  private async finishPartialRun(
    state: MirrorState,
    newRecords: Record<string, LocalRecord>,
    staging: string,
    finish: () => Promise<RunResult>,
  ): Promise<RunResult> {
    Object.assign(state.records, newRecords);
    await this.resetStaging(staging);
    return finish();
  }

  /** Stream an entry into staging in chunks, hashing as we go. Returns bytes downloaded. */
  private async download(entry: RemoteEntry, stagePath: string, signal?: AbortSignal): Promise<number> {
    const { fs, provider, settings } = this.deps;
    const hash = createSha256();
    const chunk = Math.max(1, settings.chunkSizeBytes);
    if (entry.size === 0) {
      await fs.writeBinary(stagePath, new ArrayBuffer(0));
    }
    for (let start = 0; start < entry.size; start += chunk) {
      throwIfAborted(signal);
      const end = Math.min(entry.size, start + chunk);
      const buf = await provider.readRange(entry, start, end, signal);
      if (buf.byteLength !== end - start) throw new VerifyError(`short read at ${start}`);
      hash.update(buf);
      if (start === 0) await fs.writeBinary(stagePath, buf);
      else await fs.appendBinary(stagePath, buf);
    }
    const st = await fs.stat(stagePath);
    if (!st || st.size !== entry.size) throw new VerifyError(`staged size ${st?.size ?? "missing"} != ${entry.size}`);
    if (hash.hex() !== entry.sha256) throw new VerifyError("checksum mismatch");
    return entry.size;
  }

  /** Move a verified staged file into place without losing the old copy on failure. */
  private async place(u: Upsert, stagePath: string, backupPath: string, deleteSet: Set<string>, removed: Set<string>): Promise<void> {
    const { fs, settings } = this.deps;
    const target = u.entry.path;

    if (u.fromPath) {
      await fs.remove(u.fromPath);
      removed.add(u.fromPath);
    }
    // Clear local files that occupy a folder position this file needs, and create missing folders.
    for (const dir of parentDirs(target)) {
      const st = await fs.stat(dir);
      if (st?.type === "file") {
        if (!deleteSet.has(dir)) throw new Error(`Local file blocks folder ${dir}`);
        await fs.remove(dir);
        removed.add(dir);
      }
    }
    await mkdirp(fs, parentDirs(target).pop() ?? "");

    const st = await fs.stat(target);
    if (st?.type === "folder") {
      await this.removeManagedTree(target, deleteSet, removed);
    }
    if (st?.type === "file") {
      await fs.rename(target, backupPath);
      try {
        await fs.rename(stagePath, target);
      } catch (e) {
        await fs.rename(backupPath, target);
        throw e;
      }
      await fs.remove(backupPath);
    } else {
      await fs.rename(stagePath, target);
    }

    if (u.entry.size <= settings.readbackVerifyLimitBytes) {
      if (sha256Hex(await fs.readBinary(target)) !== u.entry.sha256) throw new VerifyError("read-back checksum mismatch");
    } else {
      const after = await fs.stat(target);
      if (after?.size !== u.entry.size) throw new VerifyError("read-back size mismatch");
    }
  }

  /** Remove a local folder that must become a file. Only files already planned for deletion may go. */
  private async removeManagedTree(dir: string, deleteSet: Set<string>, removed: Set<string>): Promise<void> {
    const { fs } = this.deps;
    const { files, folders } = await fs.list(dir);
    for (const f of folders) await this.removeManagedTree(f, deleteSet, removed);
    for (const f of files) {
      if (!deleteSet.has(f)) throw new Error(`Folder ${dir} contains unmanaged file; cannot replace it with a file`);
      await fs.remove(f);
      removed.add(f);
    }
    await fs.rmdir(dir);
  }

  /** Remove managed folders that are empty and not needed by any remote file (deepest first). */
  private async removeEmptyFolders(plan: Plan, failures: SyncFailure[]): Promise<number> {
    const { fs, configDir } = this.deps;
    const needed = new Set<string>();
    for (const e of plan.manifest.entries) for (const d of parentDirs(e.path)) needed.add(collisionKey(d));
    const local = await scanFolders(fs, configDir);
    let count = 0;
    for (const dir of local.sort((a, b) => b.split("/").length - a.split("/").length)) {
      if (needed.has(collisionKey(dir))) continue;
      try {
        const { files, folders } = await fs.list(dir);
        if (files.length === 0 && folders.length === 0) {
          await fs.rmdir(dir);
          count++;
        }
      } catch (e) {
        failures.push(failureFrom(dir, e));
      }
    }
    return count;
  }

  private async resetStaging(staging: string): Promise<void> {
    const { fs } = this.deps;
    const st = await fs.stat(staging);
    if (st?.type === "folder") {
      const { files } = await fs.list(staging);
      for (const f of files) await fs.remove(f);
    } else {
      await mkdirp(fs, staging);
    }
  }
}

async function scanFolders(fs: LocalFs, configDir: string): Promise<string[]> {
  const out: string[] = [];
  const queue = [""];
  while (queue.length) {
    const { folders } = await fs.list(queue.shift()!);
    for (const f of folders) {
      if (isProtectedPath(f, configDir)) continue;
      out.push(f);
      queue.push(f);
    }
  }
  return out;
}

class VerifyError extends Error {
  readonly code = "verify_failed";
}

function record(e: RemoteEntry): LocalRecord {
  return { remoteId: e.id, path: e.path, remoteFingerprint: e.sha256, contentSha256: e.sha256, size: e.size };
}

async function pool(tasks: (() => Promise<void>)[], n: number): Promise<void> {
  let next = 0;
  const worker = async () => {
    while (next < tasks.length) await tasks[next++]!();
  };
  await Promise.all(Array.from({ length: Math.min(n, tasks.length) }, worker));
}

function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === "AbortError";
}

function failureFrom(path: string | null, e: unknown): SyncFailure {
  if (e instanceof ProviderError) return { path, code: e.code, message: e.message };
  if (e instanceof ManifestError) return { path, code: "invalid_manifest", message: e.message };
  if (e instanceof VerifyError) return { path, code: e.code, message: e.message };
  return { path, code: "error", message: e instanceof Error ? e.message : String(e) };
}

function blockMessage(b: string): string {
  switch (b) {
    case "root_changed":
      return "The bridge serves a different root than this vault was pinned to. Re-pin in settings after checking.";
    case "first_sync_nonempty":
      return "First sync requires an empty dedicated vault (or enable 'Allow non-empty first sync').";
    default:
      return b;
  }
}

function buildReport(
  status: SyncStatus,
  startedAt: string,
  finishedAt: string,
  plan: Plan | null,
  failures: SyncFailure[],
  extra: Partial<Pick<SyncReport, "applied" | "bytesDownloaded">>,
): SyncReport {
  const excludedRemote = plan ? Object.values(plan.manifest.excluded).reduce((a, b) => a + b, 0) : 0;
  return {
    status,
    startedAt,
    finishedAt,
    snapshotId: plan?.manifest.snapshotId ?? null,
    counts: {
      remote: plan?.manifest.entries.length ?? 0,
      local: plan?.localFileCount ?? 0,
      create: plan?.upserts.filter((u) => u.kind === "create").length ?? 0,
      replace: plan?.upserts.filter((u) => u.kind === "replace").length ?? 0,
      localEdits: plan?.upserts.filter((u) => u.localEdit).length ?? 0,
      delete: plan?.deletes.length ?? 0,
      unchanged: plan?.unchanged.length ?? 0,
      skippedOversize: plan?.skippedOversize.length ?? 0,
      excludedRemote,
      excludedLocal: plan?.excludedLocal ?? 0,
    },
    applied: extra.applied ?? { created: 0, replaced: 0, deleted: 0, foldersRemoved: 0 },
    bytesDownloaded: extra.bytesDownloaded ?? 0,
    hashedLocalBytes: plan?.hashedLocalBytes ?? 0,
    failures: failures.slice(0, 200),
    warnings: plan?.warnings.slice(0, 200) ?? [],
  };
}

function randomId(): string {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
