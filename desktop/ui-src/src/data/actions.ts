import { api, errorText, isFailure } from '../bridge/methods';
import { toast } from '../components/Toasts';
import type { TFunction } from '../i18n';
import type { LocalIntent } from './backendPhase';
import { createSignal } from './signal';
import { store } from './store';

export const intentSignal = createSignal<LocalIntent>(null);
export const syncBusySignal = createSignal(false);

const AFTER_START = ['server_status', 'sync_status', 'license_status', 'order_audit_status', 'fiscal_status', 'admin_credentials'];

/** Start or stop the POS server. Never claims success the backend didn't report. */
export async function runPowerAction(action: 'start' | 'stop', t: TFunction): Promise<void> {
  if (intentSignal.get()) return;
  if (action === 'stop') {
    intentSignal.set('stopping');
    try {
      const r = await api('stop_server');
      if (isFailure(r) || r.running === true) toast(errorText(r, t('dash.stopFailed')), 'danger');
      else toast(t('dash.serverOff'), 'info');
      await store.fetch('server_status');
    } finally {
      intentSignal.set(null);
    }
    return;
  }
  intentSignal.set('starting');
  try {
    const setup = await api('run_setup');
    if (isFailure(setup)) {
      toast(errorText(setup, t('dash.setupFailed')), 'danger');
      await store.fetch('server_status');
      return;
    }
    const r = await api('start_server');
    if (!isFailure(r) && r.running) toast(t('dash.serverOn'), 'ok');
    else toast(errorText(r, t('dash.startFailed')), 'danger');
    await store.fetch('server_status');
  } finally {
    intentSignal.set(null);
    store.invalidate(AFTER_START.slice(1));
  }
}

/** Manual push + pull (the background worker's cycle, on demand). */
export async function runSyncNow(t: TFunction): Promise<void> {
  if (syncBusySignal.get()) return;
  syncBusySignal.set(true);
  try {
    const r = await api('cloud_sync_now');
    if (isFailure(r)) toast(`${t('sync.down')}: ${errorText(r, t('common.failed'))}`, 'danger');
    else toast(t('dash.syncOk'), 'ok');
  } finally {
    syncBusySignal.set(false);
    store.invalidate(['sync_status']);
  }
}
