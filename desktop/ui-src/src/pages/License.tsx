import { useEffect, useMemo, useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../bridge/methods';
import type { Plan } from '../bridge/types';
import { IconArrow, IconRefresh, IconTrash, IconWarn } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { RelativeTime } from '../components/time';
import { toast } from '../components/Toasts';
import { Badge, Button, Card, ConfirmButton, Field, KeyValue, KV, Meter, Skeleton } from '../components/ui';
import { useLicenseStatus } from '../data/queries';
import { store } from '../data/store';
import { useMethodQuery } from '../data/useQuery';
import { useT, type I18nKey } from '../i18n';
import { daysLeftPct, daysUntil, fmtDate, fmtPrice } from '../lib/format';
import { FALLBACK_PLANS, findCurrentPlan, normalizePlans } from '../lib/plans';

export default function License() {
  const t = useT();
  const q = useLicenseStatus();
  const plansQ = useMethodQuery('license_plans', { gate: 'django' });
  const lic = q.data?.license;
  const registered = lic?.status === 'ACTIVE';
  const [email, setEmail] = useState('');
  const [sel, setSel] = useState<string | null>(null);
  const [busy, setBusy] = useState<'' | 'apply' | 'beat' | 'deactivate'>('');

  const fromServer = useMemo(() => (plansQ.data ? normalizePlans(plansQ.data.data) : []), [plansQ.data]);
  const offline = !fromServer.length && (plansQ.status === 'error' || (plansQ.data !== undefined && !fromServer.length));
  const plans: readonly Plan[] | null = fromServer.length ? fromServer : offline ? FALLBACK_PLANS : null;
  const current = plans ? findCurrentPlan(plans, registered, lic?.plan) : undefined;

  useEffect(() => {
    if (current) setSel(current.id);
  }, [current?.id]);

  const refreshLicense = () => store.invalidate(['license_status']);

  const apply = async () => {
    if (!sel || busy) return;
    setBusy('apply');
    try {
      if (registered) {
        const r = await api('license_plan_change', [sel, '']);
        toast(!isFailure(r) ? t('lic.planRequested') : (r.data?.message || errorText(r, t('lic.needsUrl'))), isFailure(r) ? 'danger' : 'ok');
      } else {
        const r = await api('license_register', [email || lic?.email || '', sel]);
        toast(!isFailure(r) ? t('lic.registered') : (r.data?.message || errorText(r, t('lic.needsUrl'))), isFailure(r) ? 'danger' : 'ok');
      }
    } finally {
      setBusy('');
      refreshLicense();
    }
  };

  const beat = async () => {
    setBusy('beat');
    const r = await api('license_heartbeat_now');
    setBusy('');
    toast(isFailure(r) ? errorText(r, t('dash.heartbeatFailed')) : t('dash.heartbeatOk'), !isFailure(r) ? 'ok' : r.status === 304 ? 'warn' : 'danger');
    refreshLicense();
  };

  const deactivate = async () => {
    setBusy('deactivate');
    const r = await api('license_deactivate');
    setBusy('');
    toast(isFailure(r) ? errorText(r, t('common.failed')) : t('lic.deactivated'), isFailure(r) ? 'danger' : 'info');
    refreshLicense();
  };

  const applyDisabled = !!busy || !sel || (registered ? !!current && sel === current.id : !email);
  const days = lic ? (lic.days_remaining ?? daysUntil(lic.expires_at, Date.now())) : null;

  return (
    <div class="page">
      <p class="page-sub">{t('lic.sub')}</p>
      <div class="stack">
        <Card title={t('lic.current')} actions={lic ? <Badge tone={registered ? 'ok' : 'warn'}>{t(registered ? 'common.active' : 'common.unregistered')}</Badge> : null}>
          <QueryBoundary q={q} skeleton={4}>
            {() => registered ? (
              <>
                <div class="grid">
                  <div>
                    <div class="muted small">{t('dash.org')}</div>
                    <div class="big wrap">{lic?.org_name || '—'}</div>
                    <div class="muted small">{lic?.plan || '—'}</div>
                  </div>
                  <div>
                    <div class="muted small">{t('dash.balance')}</div>
                    <div class="big">{lic?.balance ?? '—'} <span class="small muted">UZS</span></div>
                  </div>
                  <KeyValue>
                    <KV label={t('dash.expires')} mono>{fmtDate(lic?.expires_at)}</KV>
                    <KV label={t('dash.lastBeat')}><RelativeTime iso={lic?.last_heartbeat_at} /></KV>
                  </KeyValue>
                </div>
                {days !== null ? (
                  <div class="mt-4">
                    <Meter pct={daysLeftPct(days)} label={t('dash.daysLeft')} />
                    <div class="row-between small muted mt-2">
                      <span>{days} {t('dash.daysLeft')}</span>
                      <span class="mono">{fmtDate(lic?.expires_at)}</span>
                    </div>
                  </div>
                ) : null}
                {lic?.warn && lic.last_message ? (
                  <p class="row small text-warn mt-3"><IconWarn size={14} />{lic.last_message}</p>
                ) : null}
                <div class="row mt-4">
                  <Button size="sm" icon={<IconRefresh size={14} />} loading={busy === 'beat'} onClick={() => void beat()}>{t('lic.syncNow')}</Button>
                  <ConfirmButton label={t('lic.deactivate')} icon={<IconTrash size={14} />} loading={busy === 'deactivate'} onConfirm={() => void deactivate()} />
                </div>
              </>
            ) : (
              <div class="form-grid">
                <Field label={t('lic.email')} hint={t('lic.needsUrl')} htmlFor="lic-email">
                  <input
                    id="lic-email" class="input" type="email" placeholder="you@business.uz" value={email}
                    onInput={(e) => setEmail(e.currentTarget.value)}
                  />
                </Field>
              </div>
            )}
          </QueryBoundary>
        </Card>

        <Card title={t('lic.plansT')} actions={offline ? <Badge>{t('lic.plansOffline')}</Badge> : null}>
          <p class="muted small" style={{ marginBottom: '12px' }}>{t('lic.plansHint')}</p>
          {plans === null ? (
            plansQ.preparing ? <p class="muted">{t('phase.booting')}</p> : <Skeleton lines={3} />
          ) : (
            <div class="plan-grid" role="radiogroup" aria-label={t('lic.plansT')}>
              {plans.map((p) => {
                const price = fmtPrice(p.price);
                const isCurrent = current?.id === p.id;
                return (
                  <button key={p.id} type="button" class="plan" role="radio" aria-checked={sel === p.id} onClick={() => setSel(p.id)}>
                    <span class="row-between"><strong>{p.name}</strong>{isCurrent ? <Badge tone="ok">{t('lic.currentPlan')}</Badge> : null}</span>
                    <span class="small muted">{p.descKey ? t(p.descKey as I18nKey) : p.desc}</span>
                    <span class="mono">{price ? `${price} ${p.currency} / ${p.period}` : '—'}</span>
                  </button>
                );
              })}
            </div>
          )}
          <div class="mt-4">
            <Button variant="primary" icon={<IconArrow size={15} />} loading={busy === 'apply'} disabled={applyDisabled} onClick={() => void apply()}>
              {t(registered ? 'lic.switch' : 'lic.registerBtn')}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
