import { failure, normalizeResult, type BackendResult, type CallOptions, type Transport } from './transport';

export interface TauriInternals {
  invoke(command: string, args?: Record<string, unknown>): Promise<unknown>;
}

function classify(error: unknown): BackendResult {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : JSON.stringify(error);
  if (/\b403\b|forbidden|unauthori[sz]ed/i.test(message || '')) return failure('auth', 'Panel session expired', 403);
  return failure('transport', message || 'Shell bridge unavailable');
}

/** Tauri shell bridge: the Rust side proxies to the Python control server. */
export function createTauriTransport(internals: TauriInternals): Transport {
  return {
    name: 'tauri',
    call(method: string, args: unknown[], { timeoutMs, signal }: CallOptions): Promise<BackendResult> {
      return new Promise<BackendResult>((resolve) => {
        let settled = false;
        const done = (value: BackendResult) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          signal?.removeEventListener('abort', onAbort);
          resolve(value);
        };
        const onAbort = () => done(failure('transport', 'Request cancelled'));
        const timer = setTimeout(() => done(failure('timeout', `Timed out after ${Math.round(timeoutMs / 1000)}s`)), timeoutMs);
        signal?.addEventListener('abort', onAbort, { once: true });
        internals.invoke('backend_call', { method, args }).then(
          (value) => done(normalizeResult(value)),
          (error) => done(classify(error)),
        );
      });
    },
  };
}

export async function tauriRestartToUpdate(internals: TauriInternals): Promise<BackendResult> {
  try {
    const value = await internals.invoke('restart_to_update');
    return value && typeof value === 'object' ? normalizeResult(value) : { ok: true };
  } catch (error) {
    return classify(error);
  }
}
