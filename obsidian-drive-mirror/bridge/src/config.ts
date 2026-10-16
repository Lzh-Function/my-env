import { accessSync, constants, readFileSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, relative } from "node:path";

export interface BridgeConfig {
  /** Absolute path of the vault root (fixed; the plugin cannot change it). */
  root: string;
  rootId: string;
  rootName: string;
  host: string;
  port: number;
  /** sha256 hex of the bearer token. The token itself is never stored. */
  tokenSha256: string;
  allowedTailscaleLogins: string[];
  requireTailscaleIdentity: boolean;
  /** Entry that must exist under root for it to count as mounted (e.g. ".obsidian"). null disables. */
  requireMarker: string | null;
  /** Refuse to serve unless root is on a read-only mount (DESIGN D-15). */
  requireReadOnlyRoot: boolean;
  /** Delay between the two stability scans (DESIGN D-4). */
  stabilityDelayMs: number;
  maxSnapshots: number;
  stateDir: string;
}

const LOOPBACK = new Set(["127.0.0.1", "::1", "localhost"]);

export function defaultConfigPath(): string {
  return join(process.env.XDG_CONFIG_HOME ?? join(homedir(), ".config"), "drive-mirror-bridge", "config.json");
}

export function defaultStateDir(): string {
  return join(process.env.XDG_STATE_HOME ?? join(homedir(), ".local", "state"), "drive-mirror-bridge");
}

export function loadConfig(path: string): BridgeConfig {
  const raw = JSON.parse(readFileSync(path, "utf8")) as Partial<BridgeConfig>;
  const cfg: BridgeConfig = {
    root: raw.root ?? "",
    rootId: raw.rootId ?? "",
    rootName: raw.rootName ?? "",
    host: raw.host ?? "127.0.0.1",
    port: raw.port ?? 8787,
    tokenSha256: raw.tokenSha256 ?? "",
    allowedTailscaleLogins: raw.allowedTailscaleLogins ?? [],
    requireTailscaleIdentity: raw.requireTailscaleIdentity ?? true,
    requireMarker: raw.requireMarker === undefined ? ".obsidian" : raw.requireMarker,
    requireReadOnlyRoot: raw.requireReadOnlyRoot ?? true,
    stabilityDelayMs: raw.stabilityDelayMs ?? 3000,
    maxSnapshots: raw.maxSnapshots ?? 4,
    stateDir: raw.stateDir ?? defaultStateDir(),
  };
  validateConfig(cfg);
  return cfg;
}

export function validateConfig(cfg: BridgeConfig): void {
  const errors: string[] = [];
  if (!isAbsolute(cfg.root)) errors.push("root must be an absolute path");
  if (!/^[A-Za-z0-9_-]{8,}$/.test(cfg.rootId)) errors.push("rootId missing (run init)");
  if (!LOOPBACK.has(cfg.host)) errors.push("host must be a loopback address; expose via `tailscale serve` only (DESIGN D-6)");
  if (!Number.isInteger(cfg.port) || cfg.port < 1 || cfg.port > 65535) errors.push("bad port");
  if (!/^[0-9a-f]{64}$/.test(cfg.tokenSha256)) errors.push("tokenSha256 missing (run init)");
  if (cfg.requireTailscaleIdentity && cfg.allowedTailscaleLogins.length === 0) {
    errors.push("allowedTailscaleLogins is empty while requireTailscaleIdentity is true");
  }
  if (!isAbsolute(cfg.stateDir)) errors.push("stateDir must be absolute");
  if (isAbsolute(cfg.root) && isAbsolute(cfg.stateDir)) {
    const rel = relative(cfg.root, cfg.stateDir);
    if (!rel.startsWith("..") && !isAbsolute(rel)) errors.push("stateDir must not be inside root (the bridge never writes under root)");
  }
  if (errors.length) throw new Error(`Invalid bridge config:\n  - ${errors.join("\n  - ")}`);
}

/** True when this process cannot write to dir (read-only mount or no permission). */
export function isReadOnly(dir: string): boolean {
  try {
    accessSync(dir, constants.W_OK);
    return false;
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code;
    if (code === "EROFS" || code === "EACCES" || code === "EPERM") return true;
    throw e;
  }
}

/** Resolve the root, rejecting a root that is itself reached through a symlink to somewhere unexpected. */
export function resolveRoot(cfg: BridgeConfig): string {
  const real = realpathSync(cfg.root);
  if (!statSync(real).isDirectory()) throw new Error("root is not a directory");
  return real;
}
