import { failure, normalizeResult, type BackendResult, type CallOptions, type Transport } from './transport';

export function readMetaToken(doc: Document | undefined = typeof document === 'undefined' ? undefined : document): string {
  const meta = doc?.querySelector('meta[name="alpha-control-token"]');
  const value = meta?.getAttribute('content') || '';
  return value;
}

type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

/** Same-origin POST /api/<method> with the per-install control token. */
export function createHttpTransport(getToken: () => string, fetchImpl?: FetchLike): Transport {
  const doFetch: FetchLike = fetchImpl || ((input, init) => fetch(input, init));
  return {
    name: 'http',
    async call(method: string, args: unknown[], { timeoutMs, signal }: CallOptions): Promise<BackendResult> {
      const controller = new AbortController();
      let timedOut = false;
      const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
      const onAbort = () => controller.abort();
      signal?.addEventListener('abort', onAbort, { once: true });
      try {
        const response = await doFetch('/api/' + encodeURIComponent(method), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Control-Token': getToken() },
          body: JSON.stringify(args),
          signal: controller.signal,
          cache: 'no-store',
        });
        if (response.status === 403) {
          return failure('auth', 'Panel session expired', 403);
        }
        if (!response.ok) {
          return failure('http', `HTTP ${response.status}`, response.status);
        }
        let parsed: unknown;
        try {
          parsed = await response.json();
        } catch {
          return failure('http', 'Invalid JSON from the control service', response.status);
        }
        return normalizeResult(parsed);
      } catch (error) {
        if (timedOut) return failure('timeout', `Timed out after ${Math.round(timeoutMs / 1000)}s`);
        if (signal?.aborted) return failure('transport', 'Request cancelled');
        return failure('transport', error instanceof Error ? error.message : String(error));
      } finally {
        clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
      }
    },
  };
}
