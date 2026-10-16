import type { EngineSettings } from "./mirror/engine";

/** Secret ID in Obsidian SecretStorage (device-local, not part of the vault). */
export const TOKEN_SECRET_ID = "drive-mirror-bridge-token";

/** Persisted in data.json. The bridge token is NOT stored here; it lives in app.secretStorage. */
export interface DriveMirrorSettings {
  provider: "bridge" | "mock";
  bridgeUrl: string;
  maxFileSizeMiB: number;
  chunkSizeMiB: number;
  concurrency: number;
  deleteThresholdCount: number;
  deleteThresholdPercent: number;
  /** Show the preview before every apply (confirmations always force it). */
  confirmBeforeApply: boolean;
  allowNonEmptyInit: boolean;
}

export const DEFAULT_SETTINGS: DriveMirrorSettings = {
  provider: "bridge",
  bridgeUrl: "",
  maxFileSizeMiB: 512,
  chunkSizeMiB: 4,
  concurrency: 2,
  deleteThresholdCount: 20,
  deleteThresholdPercent: 20,
  confirmBeforeApply: true,
  allowNonEmptyInit: false,
};

const MiB = 1024 * 1024;
const clamp = (v: number, lo: number, hi: number, d: number) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d);

export function engineSettings(s: DriveMirrorSettings): EngineSettings {
  return {
    maxFileSizeBytes: clamp(s.maxFileSizeMiB, 1, 4096, 512) * MiB,
    chunkSizeBytes: clamp(s.chunkSizeMiB, 1, 16, 4) * MiB,
    concurrency: clamp(Math.round(s.concurrency), 1, 3, 2),
    deleteThresholdCount: clamp(s.deleteThresholdCount, 1, 1e6, 20),
    deleteThresholdRatio: clamp(s.deleteThresholdPercent, 0, 100, 20) / 100,
    allowNonEmptyInit: s.allowNonEmptyInit,
    readbackVerifyLimitBytes: 32 * MiB,
  };
}
