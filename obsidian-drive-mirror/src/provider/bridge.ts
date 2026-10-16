import { validateManifest } from "../inventory/manifest";
import { DEFAULT_RETRY, withRetry, type RetryOptions } from "../util/retry";
import { ProviderError, type RemoteEntry, type RemoteManifest, type RemoteReadProvider, type RootIdentity } from "./types";

export interface HttpRequest {
  url: string;
  method: "GET";
  headers: Record<string, string>;
}

export interface HttpResponse {
  status: number;
  /** Header names lower-cased. */
  headers: Record<string, string>;
  body: ArrayBuffer;
}

/** Transport seam: Obsidian `requestUrl` in the plugin, `fetch` in tests. Must not throw on HTTP error statuses. */
export type HttpFn = (req: HttpRequest) => Promise<HttpResponse>;

export interface BridgeConfig {
  baseUrl: string;
  token: string;
  retry?: RetryOptions;
}

const decoder = new TextDecoder();

function parseJson(res: HttpResponse): unknown {
  try {
    return JSON.parse(decoder.decode(res.body));
  } catch {
    throw new ProviderError("protocol", `Bridge returned non-JSON (HTTP ${res.status})`, res.status);
  }
}

function errorFor(res: HttpResponse, what: string): ProviderError {
  let detail = "";
  try {
    const j = JSON.parse(decoder.decode(res.body)) as { error?: unknown };
    if (typeof j.error === "string") detail = `: ${j.error}`;
  } catch {
    /* body is not JSON */
  }
  const s = res.status;
  if (s === 401 || s === 403) return new ProviderError("auth", `Bridge rejected credentials for ${what} (HTTP ${s})${detail}`, s);
  if (s === 409) return new ProviderError("conflict", `Remote changed during sync (${what})${detail}`, s);
  if (s === 429) return new ProviderError("rate_limit", `Bridge rate limited ${what}`, s);
  if (s === 503) return new ProviderError("incomplete", `Bridge could not produce a complete snapshot${detail}`, s);
  if (s >= 500) return new ProviderError("server", `Bridge error ${s} for ${what}${detail}`, s);
  return new ProviderError("protocol", `Unexpected HTTP ${s} for ${what}${detail}`, s);
}

export class BridgeProvider implements RemoteReadProvider {
  readonly kind = "bridge";
  private readonly baseUrl: string;

  constructor(
    private readonly http: HttpFn,
    private readonly config: BridgeConfig,
  ) {
    if (!/^https?:\/\//.test(config.baseUrl)) throw new ProviderError("not_configured", "Bridge URL must start with https://");
    if (!config.token) throw new ProviderError("not_configured", "Bridge token is not set");
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
  }

  private async get(path: string, what: string, extraHeaders: Record<string, string> = {}, signal?: AbortSignal): Promise<HttpResponse> {
    return withRetry(
      async () => {
        let res: HttpResponse;
        try {
          res = await this.http({
            url: this.baseUrl + path,
            method: "GET",
            headers: { Authorization: `Bearer ${this.config.token}`, ...extraHeaders },
          });
        } catch (e) {
          throw new ProviderError("network", `Cannot reach bridge (${what}): ${(e as Error).message}`);
        }
        if (res.status !== 200 && res.status !== 206) throw errorFor(res, what);
        return res;
      },
      { ...(this.config.retry ?? DEFAULT_RETRY), signal },
    );
  }

  async verifyRoot(signal?: AbortSignal): Promise<RootIdentity> {
    const j = parseJson(await this.get("/v1/root", "root", {}, signal)) as { rootIdentity?: RootIdentity };
    const r = j.rootIdentity;
    if (!r || typeof r.rootId !== "string" || typeof r.name !== "string") throw new ProviderError("protocol", "Bridge /v1/root missing rootIdentity");
    return { rootId: r.rootId, name: r.name };
  }

  async listCompleteTree(signal?: AbortSignal): Promise<RemoteManifest> {
    return validateManifest(parseJson(await this.get("/v1/manifest", "manifest", {}, signal)));
  }

  async readRange(entry: RemoteEntry, start: number, end: number, signal?: AbortSignal): Promise<ArrayBuffer> {
    if (end <= start) return new ArrayBuffer(0);
    const res = await this.get(
      `/v1/file/${encodeURIComponent(entry.id)}`,
      "file",
      { Range: `bytes=${start}-${end - 1}` },
      signal,
    );
    const full = res.status === 200;
    if (full && !(start === 0 && end === entry.size)) throw new ProviderError("protocol", "Bridge ignored Range request");
    if (res.body.byteLength !== end - start) {
      throw new ProviderError("protocol", `Short read: expected ${end - start} bytes, got ${res.body.byteLength}`);
    }
    const sha = res.headers["x-content-sha256"];
    if (sha !== undefined && sha !== entry.sha256) throw new ProviderError("conflict", "File hash changed since listing");
    return res.body;
  }

  async signOut(): Promise<void> {
    // Credentials live in plugin settings; the caller clears them. Nothing to revoke remotely.
  }
}
