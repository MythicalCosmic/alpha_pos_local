import type { ShiftCloseStatus, SyncState } from '../bridge/types';

export type Tone = 'ok' | 'warn' | 'danger' | 'muted' | 'info';

export type SyncLabel =
  | 'sync.busy' | 'sync.closeConflict' | 'sync.closePending' | 'sync.replayPending'
  | 'sync.off' | 'sync.live' | 'sync.down';

export interface SyncPillState {
  tone: Tone;
  label: SyncLabel;
  pending: number;
  replayPending: boolean;
  closeConflict: boolean;
  closePending: boolean;
  /** Distinct raw backend messages worth surfacing as a tooltip / detail. */
  details: string[];
}

export function shiftCloseState(close: ShiftCloseStatus | undefined): { conflict: boolean; pending: boolean } {
  const c = close || {};
  const state = String(c.state || '').toUpperCase();
  const conflict = state === 'CONFLICT' || Number(c.conflict_count || 0) > 0;
  const pending = !conflict && (state === 'PENDING' || Number(c.pending_count || 0) > 0);
  return { conflict, pending };
}

/** Full cloud replay requested but not yet completed (durable flag or state). */
export function isReplayPending(sync: SyncState | undefined): boolean {
  if (!sync) return false;
  return !!sync.full_pull_pending || String(sync.full_pull_state || '').toLowerCase() === 'pending';
}

/**
 * The titlebar sync chip. Priority: busy > shift-close conflict > shift-close
 * pending > full replay pending > sync disabled > online > not connected.
 */
export function deriveSyncPill(sync: SyncState | undefined, busy = false): SyncPillState {
  const s = sync || {};
  const enabled = !!s.enabled;
  const online = enabled && !!s.is_online;
  const close = s.shift_close || {};
  const { conflict, pending: closePending } = shiftCloseState(close);
  const replayPending = isReplayPending(s);
  const tone: Tone = conflict
    ? 'danger'
    : closePending || replayPending
      ? 'warn'
      : !enabled ? 'muted' : online ? 'ok' : 'danger';
  const label: SyncLabel = busy
    ? 'sync.busy'
    : conflict ? 'sync.closeConflict'
      : closePending ? 'sync.closePending'
        : replayPending ? 'sync.replayPending'
          : !enabled ? 'sync.off' : online ? 'sync.live' : 'sync.down';
  const details = [close.message || '', s.last_pull_error || '', s.last_error || '']
    .map((v) => String(v).trim())
    .filter((v, i, all) => v && all.indexOf(v) === i);
  return {
    tone, label, pending: Number(s.pending_count || 0), replayPending,
    closeConflict: conflict, closePending, details,
  };
}
