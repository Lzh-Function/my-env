// Read-only remote abstraction. There are deliberately no write/delete/rename methods (DESIGN §12).

export interface RootIdentity {
  rootId: string;
  name: string;
}

export interface RemoteEntry {
  id: string; // opaque, valid only within its snapshot
  path: string; // vault-relative POSIX path
  size: number;
  modifiedTime: string | null;
  sha256: string; // lowercase hex
}

export interface RemoteManifest {
  schemaVersion: 1;
  snapshotId: string;
  complete: true;
  generatedAt: string;
  rootIdentity: RootIdentity;
  entries: RemoteEntry[];
  /** Counts of remote items intentionally not mirrored, by reason (hidden, symlink, google_native, ...). */
  excluded: Record<string, number>;
}

export interface RemoteReadProvider {
  readonly kind: string;
  verifyRoot(signal?: AbortSignal): Promise<RootIdentity>;
  listCompleteTree(signal?: AbortSignal): Promise<RemoteManifest>;
  /** Bytes [start, end) of the entry as of its snapshot. */
  readRange(entry: RemoteEntry, start: number, end: number, signal?: AbortSignal): Promise<ArrayBuffer>;
  signOut(): Promise<void>;
}

export type ProviderErrorCode =
  | "auth" // 401/403: credentials or identity rejected
  | "incomplete" // bridge could not produce a complete snapshot
  | "conflict" // 409: snapshot expired or file changed since listing
  | "rate_limit"
  | "server"
  | "network"
  | "protocol" // malformed response
  | "not_configured";

export class ProviderError extends Error {
  constructor(
    readonly code: ProviderErrorCode,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = "ProviderError";
  }

  get retryable(): boolean {
    return this.code === "rate_limit" || this.code === "server" || this.code === "network";
  }
}
