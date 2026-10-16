import { ProviderError } from "../provider/types";

export interface RetryOptions {
  attempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  signal?: AbortSignal;
}

export const DEFAULT_RETRY: RetryOptions = { attempts: 4, baseDelayMs: 500, maxDelayMs: 8000 };

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new DOMException("Sync cancelled", "AbortError");
}

/** Retry only errors that are explicitly retryable (429 / 5xx / network). Auth and conflict errors surface at once. */
export async function withRetry<T>(fn: () => Promise<T>, opts: RetryOptions = DEFAULT_RETRY): Promise<T> {
  const sleep = opts.sleep ?? defaultSleep;
  const random = opts.random ?? Math.random;
  for (let attempt = 1; ; attempt++) {
    throwIfAborted(opts.signal);
    try {
      return await fn();
    } catch (e) {
      if (!(e instanceof ProviderError) || !e.retryable || attempt >= opts.attempts) throw e;
      const exp = Math.min(opts.maxDelayMs, opts.baseDelayMs * 2 ** (attempt - 1));
      await sleep(exp / 2 + random() * (exp / 2));
    }
  }
}
