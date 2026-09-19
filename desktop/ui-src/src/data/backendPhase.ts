import type { ServerStatus } from '../bridge/types';

export type BackendPhase =
  | 'connecting' | 'unreachable' | 'booting' | 'starting'
  | 'stopping' | 'running' | 'error' | 'stopped';

export type LocalIntent = 'starting' | 'stopping' | null;

export interface ServerQueryView {
  data: ServerStatus | undefined;
  /** Consecutive transport/timeout failures of server_status. */
  transportFailures: number;
}

export const UNREACHABLE_AFTER = 2;

/** First non-empty problem the backend reports while stopped. */
export function serverProblem(data: ServerStatus | undefined): string {
  if (!data) return '';
  return String(
    data.setup_error || data.environment?.error || data.database?.error || data.last_error || '',
  ).trim();
}

/**
 * Pure mapping from the server_status query (+ the operator's in-flight click)
 * to what the panel shows. Never reports "stopped" while the backend is still
 * booting towards a desired running state.
 */
export function deriveBackendPhase(query: ServerQueryView, intent: LocalIntent): BackendPhase {
  if (query.transportFailures >= UNREACHABLE_AFTER) return 'unreachable';
  const s = query.data;
  if (!s) return 'connecting';
  const phase = s.phase ?? (s.running ? 'running' : 'stopped');
  if (phase === 'stopping' || (intent === 'stopping' && phase !== 'stopped')) return 'stopping';
  if (phase === 'starting' || (intent === 'starting' && phase !== 'running')) return 'starting';
  if (phase === 'running') {
    if (s.desired_running && s.django_ready === false) return 'booting';
    return 'running';
  }
  // Stopped (or unknown) phase from here on.
  if (s.desired_running) return 'booting';
  if (serverProblem(s)) return 'error';
  return 'stopped';
}

export function powerAction(phase: BackendPhase): 'start' | 'stop' | null {
  if (phase === 'running') return 'stop';
  if (phase === 'stopped' || phase === 'error') return 'start';
  return null;
}

export function isTransitional(phase: BackendPhase): boolean {
  return phase === 'starting' || phase === 'stopping' || phase === 'booting' || phase === 'connecting';
}
