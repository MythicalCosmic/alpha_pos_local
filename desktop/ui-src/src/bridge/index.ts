import { createHttpTransport, readMetaToken } from './http';
import { createTauriTransport, tauriRestartToUpdate, type TauriInternals } from './tauri';
import { failure, type BackendResult, type CallOptions, type Capabilities, type Transport } from './transport';

export type { BackendResult, BridgeErrorKind, BridgeFailure, Capabilities, Transport } from './transport';

interface BridgeOverride {
  token?: string;
  call?: Transport['call'];
  capabilities?: Partial<Capabilities>;
}

declare global {
  interface Window {
    __ALPHA_BRIDGE__?: BridgeOverride;
    __TAURI_INTERNALS__?: TauriInternals;
    __alphaHasUnsavedChanges?: () => boolean;
  }
}

export interface BridgeSelection {
  transport: Transport;
  capabilities: Capabilities;
  restartToUpdate: () => Promise<BackendResult>;
}

/** Transport order: explicit __ALPHA_BRIDGE__ override → Tauri → same-origin HTTP. */
export function selectBridge(win: Window | undefined = typeof window === 'undefined' ? undefined : window): BridgeSelection {
  const unsupported = async () => failure('http', 'Restart to update is not available in this shell');
  const override = win?.__ALPHA_BRIDGE__;
  if (override && typeof override.call === 'function') {
    const call = override.call;
    return {
      transport: { name: 'custom', call: (m, a, o) => call(m, a, o) },
      capabilities: { shell: 'legacy', restartToUpdate: false, ...override.capabilities },
      restartToUpdate: unsupported,
    };
  }
  const internals = win?.__TAURI_INTERNALS__;
  if (internals && typeof internals.invoke === 'function') {
    return {
      transport: createTauriTransport(internals),
      capabilities: { shell: 'tauri', restartToUpdate: true },
      restartToUpdate: () => tauriRestartToUpdate(internals),
    };
  }
  const token = override?.token;
  return {
    transport: createHttpTransport(() => token || readMetaToken()),
    capabilities: { shell: 'legacy', restartToUpdate: false, ...override?.capabilities },
    restartToUpdate: unsupported,
  };
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

export function capabilities(): Capabilities {
  return current().capabilities;
}

export function restartToUpdate(): Promise<BackendResult> {
  return current().restartToUpdate();
}

/** Test seam: replace the selected transport. */
export function setBridgeForTests(next: BridgeSelection | null): void {
  selection = next;
}
