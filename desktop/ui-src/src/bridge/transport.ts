// Transport contract of the panel bridge (HTTP to control_server.py, or a test
// override). A transport NEVER throws: every failure is
// normalized into a BridgeFailure so screens can render it.

export type BridgeErrorKind = 'transport' | 'timeout' | 'auth' | 'http';

export type BridgeFailure = {
  ok: false;
  error: string;
  kind: BridgeErrorKind;
  status?: number;
};

/** Backend results are JSON objects: `{ok: true, ...}` or `{ok: false, error}`. */
export interface BackendResult {
  ok?: boolean;
  error?: string | null;
  kind?: BridgeErrorKind;
  [key: string]: unknown;
}

export interface CallOptions {
  timeoutMs: number;
  signal?: AbortSignal;
}

export interface Transport {
  readonly name: 'http' | 'custom';
  call(method: string, args: unknown[], options: CallOptions): Promise<BackendResult>;
}

export function failure(kind: BridgeErrorKind, error: string, status?: number): BridgeFailure {
  return status === undefined ? { ok: false, error, kind } : { ok: false, error, kind, status };
}

/** Accept only plain JSON objects as results; anything else is an HTTP-level fault. */
export function normalizeResult(value: unknown): BackendResult {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as BackendResult;
  return failure('http', 'Unexpected response from the control service');
}
