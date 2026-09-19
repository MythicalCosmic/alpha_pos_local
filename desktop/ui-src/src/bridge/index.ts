import { createHttpTransport, readMetaToken } from './http';
import { failure, type BackendResult, type CallOptions, type Transport } from './transport';

export type { BackendResult, BridgeErrorKind, BridgeFailure, Transport } from './transport';

interface BridgeOverride {
  token?: string;
  call?: Transport['call'];
}

declare global {
  interface Window {
    __ALPHA_BRIDGE__?: BridgeOverride;
    __alphaHasUnsavedChanges?: () => boolean;
  }
}

export interface BridgeSelection {
  transport: Transport;
}

/**
 * Transport order: explicit __ALPHA_BRIDGE__ override → same-origin HTTP to the
 * control server that served the page (one thread per request, the panel's own
 * per-method timeouts).
 */
export function selectBridge(win: Window | undefined = typeof window === 'undefined' ? undefined : window): BridgeSelection {
  const override = win?.__ALPHA_BRIDGE__;
  if (override && typeof override.call === 'function') {
    const call = override.call;
    return {
      transport: { name: 'custom', call: (m, a, o) => call(m, a, o) },
    };
  }
  const token = override?.token;
  const pageToken = () => token || readMetaToken(win?.document);
  return { transport: createHttpTransport(pageToken) };
}

let selection: BridgeSelection | null = null;
function current(): BridgeSelection {
  if (!selection) selection = selectBridge();
  return selection;
}

type AuthListener = () => void;
const authListeners = new Set<AuthListener>();
export function onAuthError(listener: AuthListener): () => void {
  authListeners.add(listener);
  return () => authListeners.delete(listener);
}

export async function rawCall(method: string, args: unknown[], options: CallOptions): Promise<BackendResult> {
  let result: BackendResult;
  try {
    result = await current().transport.call(method, args, options);
  } catch (error) {
    result = failure('transport', error instanceof Error ? error.message : String(error));
  }
  if (result.kind === 'auth') authListeners.forEach((listener) => listener());
  return result;
}

/** Test seam: replace the selected transport. */
export function setBridgeForTests(next: BridgeSelection | null): void {
  selection = next;
}
