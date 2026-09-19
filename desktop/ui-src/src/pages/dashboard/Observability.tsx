// Below-the-fold dashboard section (support tunnel + order evidence). Loaded
// as its own chunk right after the dashboard paints.
import { useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../../bridge/methods';
import type { OrderAuditStatus, TunnelStatus } from '../../bridge/types';
import { IconSend } from '../../components/icons';
import { QueryBoundary } from '../../components/QueryBoundary';
import { toast } from '../../components/Toasts';
import { Badge, Button, Card, KeyValue, KV, Switch } from '../../components/ui';
import { useOrderAuditStatus, useTunnelStatus } from '../../data/queries';
import { store } from '../../data/store';
import { useT } from '../../i18n';
import { fmtBytes } from '../../lib/format';
import type { Tone } from '../../lib/sync';
import { navigate } from '../../router/router';

/** Optimistic toggle: patch the cached status, roll back on failure. */
async function optimistic<T extends TunnelStatus | OrderAuditStatus>(
  key: string,
  patch: Partial<T>,
  call: () => Promise<Record<string, unknown>>,
  messages: { ok: string; failed: string },
): Promise<void> {
  const previous = store.getState(key).data;
  store.setData(key, (d) => ({ ...(d || {}), ...patch }));
  const r = await call();
  if (isFailure(r)) {
    store.setData(key, () => previous);
    toast(errorText(r, messages.failed), 'danger');
  } else {
    store.setData(key, () => r);
    toast(messages.ok, 'ok');
  }
  store.invalidate([key]);
}

export default function Observability() {
  return (
    <div class="grid-2">
      <TunnelCard />
      <OrderAuditCard />
    </div>
  );
}

function TunnelCard() {
  const t = useT();
  const q = useTunnelStatus();
  const [busy, setBusy] = useState(false);
  const d = q.data;
  // A tunnel that is switched off is not a problem: the backend still reports
  // "host is not valid" for the blank default, which must not read as an error.
  const tone: Tone = !d?.enabled ? 'muted' : d.ready ? 'ok' : d.state === 'error' ? 'danger' : 'warn';
  const label = t(!d?.enabled ? 'common.offline' : d.ready ? 'obs.tunnelReady' : 'obs.tunnelWaiting');
  const error = d?.enabled ? d.configuration_error || d.last_error || (!d.ready ? d.last_probe_error : '') : '';
  const toggle = async (on: boolean) => {
    if (busy) return;
    setBusy(true);
    await optimistic<TunnelStatus>(
      'support_tunnel_status',
      { enabled: on, ready: false, state: on ? 'connecting' : 'off' },
      () => api('set_support_tunnel_enabled', [on]),
      { ok: t(on ? 'obs.tunnelEnabled' : 'obs.tunnelDisabled'), failed: t('common.failed') },
    );
    setBusy(false);
  };
  return (
    <Card
      title={t('obs.tunnelTitle')}
      actions={d ? (
        <>
          <Badge tone={tone}>{label}</Badge>
          <Switch checked={!!d.enabled} label={t('obs.tunnelTitle')} disabled={busy} onChange={(on) => void toggle(on)} />
        </>
      ) : null}
    >
      <QueryBoundary q={q} skeleton={4}>
        {(s) => (
          <>
            <div class="row">
              <Badge tone={s.db_ready ? 'ok' : s.enabled ? 'warn' : 'muted'}>{s.db_label || s.db_status || t('obs.notVerified')}</Badge>
              <Badge tone={s.backend_ready ? 'ok' : s.enabled ? 'warn' : 'muted'}>{s.backend_label || s.backend_status || t('obs.notVerified')}</Badge>
            </div>
            {error ? <p class="small text-danger wrap mt-2">{error}</p> : null}
            {!s.configured && s.enabled ? <p class="small text-warn mt-2">{t('obs.tunnelConfigure')}</p> : null}
            <p class="small muted mt-2">{t('obs.tunnelHint')}</p>
            <details class="tech mt-2">
              <summary>{t('dash.technical')}</summary>
              <KeyValue>
                <KV label={t('obs.dbReadiness')}>{s.db_status || '—'}</KV>
                <KV label={t('obs.backendReadiness')}>{s.backend_status || '—'}</KV>
                <KV label={t('obs.dbQuery')}>{t(s.local_db_query_verified ? 'obs.verified' : 'obs.notVerified')}</KV>
                <KV label={t('obs.secureSession')}>{t(s.session_verified ? 'common.online' : 'common.offline')}</KV>
                <KV label={t('obs.relayHost')} mono dim={!s.relay_host}>{s.relay_host || '—'}</KV>
                <KV label={t('obs.relayDb')} mono dim={!s.remote_db}>{s.remote_db || '—'}</KV>
                <KV label={t('obs.relayApi')} mono dim={!s.remote_api}>{s.remote_api || '—'}</KV>
                <KV label={t('obs.hostFingerprint')} mono dim={!s.pinned_host_fingerprint}>{s.pinned_host_fingerprint || '—'}</KV>
                <KV label={t('obs.connectorArtifact')} mono dim={!s.connector_artifact}>{s.connector_artifact || '—'}</KV>
                <KV label={t('obs.operatorDb')} mono dim={!s.operator_db}>{s.operator_db || '—'}</KV>
                <KV label={t('obs.operatorApi')} mono dim={!s.operator_api}>{s.operator_api || '—'}</KV>
                <KV label={t('obs.retryState')} mono dim={!s.next_retry_at}>
                  {s.next_retry_at ? `${s.retry_backoff_seconds || 0}s · ${s.next_retry_at}` : t('obs.noRetry')}
                </KV>
              </KeyValue>
              {s.operator_readiness_instruction ? (
                <p class="small muted mt-2"><strong>{t('obs.operatorInstruction')}:</strong> {s.operator_readiness_instruction}</p>
              ) : null}
            </details>
          </>
        )}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" onClick={() => navigate('config')}>{t('common.manage')}</Button>
      </div>
    </Card>
  );
}

function OrderAuditCard() {
  const t = useT();
  const q = useOrderAuditStatus();
  const [busy, setBusy] = useState<'' | 'collect' | 'send' | 'now'>('');
  const d = q.data;
  // "Not set up yet" is the state of every new install, not a fault.
  const unconfigured = d?.delivery_state === 'configuration_required' || d?.telegram_configured === false;
  const error = d?.delivery_state === 'error' && !unconfigured;
  const active = d?.enabled !== false && d?.auto_send !== false;
  const tone: Tone = error ? 'danger' : unconfigured ? 'muted' : active ? 'ok' : 'muted';
  const label = t(error ? 'obs.needsAttention' : unconfigured ? 'obs.notSetUp' : active ? 'obs.telegramActive' : 'obs.paused');

  const toggle = async (field: 'enabled' | 'auto_send', on: boolean) => {
    if (busy) return;
    setBusy(field === 'enabled' ? 'collect' : 'send');
    await optimistic<OrderAuditStatus>(
      'order_audit_status',
      { [field]: on },
      () => api(field === 'enabled' ? 'set_order_audit_enabled' : 'set_order_audit_auto_send', [on]),
      {
        ok: t(field === 'enabled'
          ? (on ? 'audit.enabledToast' : 'audit.disabledToast')
          : (on ? 'audit.autoEnabledToast' : 'audit.autoDisabledToast')),
        failed: t('common.failed'),
      },
    );
    setBusy('');
  };
  const sendNow = async () => {
    if (busy) return;
    setBusy('now');
    const r = await api('send_order_audit_now');
    setBusy('');
    store.invalidate(['order_audit_status']);
    if (r.ok !== false || r.partial) toast(t(r.partial ? 'audit.sentPartial' : 'audit.sent'), r.partial ? 'warn' : 'ok');
    else toast(r.failed?.[0]?.error || errorText(r, t('audit.sendFailed')), 'danger');
  };

  return (
    <Card title={t('obs.auditTitle')} actions={d ? <Badge tone={tone}>{label}</Badge> : null}>
      <QueryBoundary q={q} skeleton={4}>
        {(s) => (
          <>
            <div class="toggle-row">
              <div>
                <div>{t('audit.collect')}</div>
                <div class="small muted">{t('obs.collectShort')}</div>
              </div>
              <Switch checked={s.enabled !== false} label={t('audit.collect')} disabled={!!busy} onChange={(on) => void toggle('enabled', on)} />
            </div>
            <div class="toggle-row">
              <div>
                <div>{t('audit.autoSend')}</div>
                <div class="small muted">{t('obs.telegramDirect')}</div>
              </div>
              <Switch checked={s.auto_send !== false} label={t('audit.autoSend')} disabled={!!busy} onChange={(on) => void toggle('auto_send', on)} />
            </div>
            <KeyValue>
              <KV label={t('obs.ordersCaptured')} mono>{s.order_count || 0}</KV>
              <KV label={t('obs.pendingEvidence')} mono>{fmtBytes(s.auto_pending_bytes)}</KV>
              <KV label={t('obs.telegramChats')} mono>{s.telegram_chat_count || 0}</KV>
              <KV label={t('obs.formats')} mono>{(s.formats || ['JSONL', 'JSONL.GZ']).join(' + ')}</KV>
            </KeyValue>
            {error && (s.last_auto_send_error || s.last_error) ? <p class="small text-danger wrap mt-2">{s.last_auto_send_error || s.last_error}</p> : null}
            {unconfigured ? <p class="small muted mt-2">{t('obs.telegramConfigure')}</p> : null}
            <p class="small muted mt-2">{t('obs.auditHint')}</p>
          </>
        )}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" variant="primary" icon={<IconSend size={14} />} loading={busy === 'now'} disabled={!d} onClick={() => void sendNow()}>
          {t(busy === 'now' ? 'audit.sending' : 'audit.sendNow')}
        </Button>
        <Button size="sm" onClick={() => navigate('local-audit')}>{t('common.manage')}</Button>
      </div>
    </Card>
  );
}
