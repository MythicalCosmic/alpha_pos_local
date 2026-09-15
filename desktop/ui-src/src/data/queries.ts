// Shared query hooks. The shell and pages subscribe to the same keys, so the
// store dedupes requests and polls at the fastest active interval.
import { deriveBackendPhase, isTransitional, type BackendPhase } from './backendPhase';
import { intentSignal } from './actions';
import { useSignal } from './signal';
import { store } from './store';
import { SERVER_KEY, useMethodQuery } from './useQuery';
import type { ServerStatus } from '../bridge/types';

export const POLL = {
  serverFast: 3_000,
  server: 5_000,
  sync: 10_000,
  tunnel: 10_000,
  audit: 15_000,
  updateShell: 60_000,
  updatePage: 5_000,
  license: 30_000,
  fiscal: 30_000,
  localAudit: 5_000,
  logsLive: 5_000,
} as const;

export function useBackend() {
  const intent = useSignal(intentSignal);
  const snapshot = store.getState(SERVER_KEY);
  const before = deriveBackendPhase(
    { data: snapshot.data as ServerStatus | undefined, transportFailures: snapshot.transportFailures },
    intent,
  );
  const q = useMethodQuery('server_status', { interval: isTransitional(before) ? POLL.serverFast : POLL.server });
  const phase: BackendPhase = deriveBackendPhase(
    { data: q.data as ServerStatus | undefined, transportFailures: q.transportFailures },
    intent,
  );
  return { q, phase, server: q.data as ServerStatus | undefined };
}

export const useSyncStatus = () => useMethodQuery('sync_status', { interval: POLL.sync, gate: 'django' });
export const useTunnelStatus = () => useMethodQuery('support_tunnel_status', { interval: POLL.tunnel });
export const useOrderAuditStatus = () => useMethodQuery('order_audit_status', { interval: POLL.audit, gate: 'django' });
export const useUpdateStatus = (interval: number = POLL.updateShell) => useMethodQuery('update_status', { interval });
export const useLicenseStatus = () => useMethodQuery('license_status', { interval: POLL.license, gate: 'django' });
export const useFiscalStatus = () => useMethodQuery('fiscal_status', { interval: POLL.fiscal, gate: 'django' });
export const useAdminCredentials = () => useMethodQuery('admin_credentials');
