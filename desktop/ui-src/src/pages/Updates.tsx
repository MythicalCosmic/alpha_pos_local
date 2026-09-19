import { useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../bridge/methods';
import { IconDownload, IconRefresh } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { toast } from '../components/Toasts';
import { Badge, Banner, Button, Card, EmptyState, KeyValue, KV } from '../components/ui';
import { POLL, useUpdateStatus } from '../data/queries';
import { store } from '../data/store';
import { useT } from '../i18n';
import { fmtBytes, fmtDateTime } from '../lib/format';

export default function Updates() {
  const t = useT();
  const q = useUpdateStatus(POLL.updatePage);
  const [busy, setBusy] = useState<'' | 'check' | 'install'>('');
  const u = q.data;
  const newer = !!(u?.available && u.available !== u.version);

  const check = async () => {
    setBusy('check');
    const r = await api('check_updates_only');
    setBusy('');
    store.invalidate(['update_status']);
    if (isFailure(r) || (typeof r.error === 'string' && r.error)) toast(errorText(r, t('upd.checkFailed')), 'danger');
    else if (r.busy) toast(t('upd.checking'), 'info');
    else if (r.available && r.available !== u?.version) toast(t('upd.newAvailable'), 'info');
    else if (r.enabled !== false) toast(t('upd.upToDate'), 'ok');
    else toast(r.reason || t('upd.disabledMode'), 'warn');
  };

  const install = async () => {
    setBusy('install');
    const r = await api('check_updates_now');
    setBusy('');
    if (isFailure(r)) toast(errorText(r, t('common.failed')), 'danger');
    store.invalidate(['update_status']);
  };

  return (
    <div class="page">
      <p class="page-sub">{t('upd.sub')}</p>
      <div class="stack">
        <Card
          title={t('upd.current')}
          actions={u ? (
            <Badge tone={u.active || u.pending || newer ? 'warn' : 'ok'}>
              {t(u.active ? 'upd.installing' : u.pending ? 'upd.pending' : newer ? 'upd.newAvailable' : 'upd.upToDate')}
            </Badge>
          ) : null}
        >
          <QueryBoundary q={q} skeleton={6}>
            {(d) => {
              const pct = Math.max(0, Math.min(100, Number(d.progress || 0)));
              return (
                <>
                  <div class="grid">
                    <div>
                      <div class="muted small">{t('upd.version')}</div>
                      <div class="big mono">{d.version ? `v${d.version}` : '—'}</div>
                    </div>
                    <KeyValue>
                      <KV label={t('upd.mode')}>{t(!d.frozen ? 'upd.dev' : d.enabled === false ? 'upd.disabledMode' : 'upd.installed')}</KV>
                      <KV label={t('upd.server')} mono dim={!d.update_url}>{d.update_url || t('common.none')}</KV>
                      <KV label={t('upd.availableV')} mono>{d.available ? `v${d.available}` : t('upd.upToDate')}</KV>
                    </KeyValue>
                  </div>
                  <div class="mt-3">
                    <KeyValue>
                      <KV label={t('upd.lastChecked')} dim={!d.last_check_at}>{d.last_check_at ? fmtDateTime(d.last_check_at) : t('upd.never')}</KV>
                      <KV label={t('upd.lastUpdated')} dim={!d.last_update_at}>
                        {d.last_update_at ? `${fmtDateTime(d.last_update_at)}${d.last_update_version ? ` · v${d.last_update_version}` : ''}` : t('upd.never')}
                      </KV>
                      {d.last_check_error ? <KV label={t('upd.lastError')}><span class="text-warn">{d.last_check_error}</span></KV> : null}
                    </KeyValue>
                  </div>
                  {d.pending ? <div class="mt-3"><Banner tone="warn">{t('upd.pendingMsg')}</Banner></div> : null}
                  {d.active || (d.phase && d.phase !== 'idle') ? (
                    <div class="mt-3" aria-label={t('upd.progress')} role="group">
                      <div class="row-between small">
                        <span class="wrap">{d.message || d.phase}</span>
                        <span class="mono">{d.bytes_total ? `${fmtBytes(d.bytes_downloaded)} / ${fmtBytes(d.bytes_total)} · ` : ''}{pct}%</span>
                      </div>
                      <div class="progress mt-2" role="progressbar" aria-label={t('upd.progress')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                        <i style={{ width: `${pct}%` }} />
                      </div>
                    </div>
                  ) : null}
                </>
              );
            }}
          </QueryBoundary>
          <div class="row mt-4">
            <Button icon={<IconRefresh size={14} />} loading={busy === 'check'} disabled={!!busy || !!u?.active} onClick={() => void check()}>
              {t(busy === 'check' ? 'upd.checking' : 'upd.checkNow')}
            </Button>
            <Button variant="primary" icon={<IconDownload size={14} />} loading={busy === 'install'} disabled={!!busy || !!u?.active || !newer} onClick={() => void install()}>
              {t(u?.active ? 'upd.installing' : 'upd.installNow')}
            </Button>
          </div>
          <p class="small muted mt-3">{t('upd.auto')}</p>
        </Card>

        <Card title={t('upd.history')}>
          {u?.history?.length ? (
            <KeyValue>
              {u.history.slice().reverse().map((h, i) => <KV key={i} label={fmtDateTime(h.at)} mono>{h.version ? `v${h.version}` : '—'}</KV>)}
            </KeyValue>
          ) : u ? <EmptyState>{t('upd.noHistory')}</EmptyState> : null}
        </Card>
      </div>
    </div>
  );
}
