import type { ComponentType } from 'preact';
import { useEffect, useState } from 'preact/hooks';
import { capabilities, restartToUpdate } from '../bridge';
import { api, errorText, isFailure } from '../bridge/methods';
import { IconEye, IconPower, IconRefresh } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { RelativeTime, Uptime } from '../components/time';
import { toast } from '../components/Toasts';
import {
  Badge, Banner, Button, Card, CopyButton, IconButton, KeyValue, KV, Meter, Skeleton, StatusDot,
} from '../components/ui';
import { runPowerAction, runSyncNow, syncBusySignal } from '../data/actions';
import { isTransitional, powerAction, serverProblem, type BackendPhase } from '../data/backendPhase';
import {
  useAdminCredentials, useBackend, useFiscalStatus, useLicenseStatus, useSyncStatus, useUpdateStatus,
} from '../data/queries';
import { useSignal } from '../data/signal';
import { store } from '../data/store';
import { useT, type I18nKey } from '../i18n';
import { daysLeftPct, daysUntil, fmtDate, hostFromUrl } from '../lib/format';
import { deriveSyncPill, shiftCloseState, type Tone } from '../lib/sync';
import { navigate } from '../router/router';

const PHASE_TITLE: Record<BackendPhase, I18nKey> = {
  running: 'dash.serverOn',
  starting: 'chip.starting',
  stopping: 'dash.stopping',
  booting: 'phase.booting',
  connecting: 'phase.connecting',
  unreachable: 'phase.unreachable',
  error: 'phase.error',
  stopped: 'dash.serverOff',
};
const PHASE_SUB: Partial<Record<BackendPhase, I18nKey>> = {
  running: 'dash.serverOnSub',
  stopped: 'dash.serverOffSub',
  booting: 'phase.bootingSub',
  unreachable: 'phase.unreachableSub',
  error: 'phase.errorSub',
};
const PHASE_TONE: Record<BackendPhase, Tone> = {
  running: 'ok', starting: 'warn', stopping: 'warn', booting: 'warn',
  connecting: 'muted', unreachable: 'danger', error: 'danger', stopped: 'muted',
};
const FIS_MODE: Record<string, I18nKey> = {
  off: 'fis.off', mock: 'fis.mock', sandbox: 'fis.sandbox', live: 'fis.live',
};

export default function Dashboard() {
  const t = useT();
  return (
    <div class="page">
      <p class="page-sub">{t('dash.sub')}</p>
      <ShiftCloseBanner />
      <div class="grid-2">
        <ServerCard />
        <SignInCard />
      </div>
      <div class="grid mt-4">
        <SyncTile />
        <HeartbeatTile />
        <LicenseTile />
        <FiscalTile />
        <UpdatesTile />
      </div>
      <h2 class="section-title">{t('dash.observability')}</h2>
      <p class="page-sub">{t('obs.sub')}</p>
      <LazyObservability />
    </div>
  );
}

let observabilityModule: ComponentType | null = null;

function LazyObservability() {
  const [Section, setSection] = useState<ComponentType | null>(() => observabilityModule);
  useEffect(() => {
    if (Section) return undefined;
    let live = true;
    void import('./dashboard/Observability').then((m) => {
      observabilityModule = m.default;
      if (live) setSection(() => m.default);
    });
    return () => { live = false; };
  }, []);
  if (Section) return <Section />;
  return (
    <div class="grid-2">
      <Card><Skeleton lines={5} /></Card>
      <Card><Skeleton lines={5} /></Card>
    </div>
  );
}

function ShiftCloseBanner() {
  const t = useT();
  const { data } = useSyncStatus();
  const close = data?.sync?.shift_close;
  const { conflict, pending } = shiftCloseState(close);
  if (!conflict && !pending) return null;
  return (
    <div style={{ marginBottom: '16px' }}>
      <Banner tone={conflict ? 'danger' : 'warn'} role="alert" title={t(conflict ? 'obs.closeConflict' : 'obs.closePending')}>
        {close?.message || t('obs.closePendingHint')}
      </Banner>
    </div>
  );
}

function ServerCard() {
  const t = useT();
  const { phase, server } = useBackend();
  const action = powerAction(phase);
  const sub = PHASE_SUB[phase];
  const problem = phase === 'running' ? '' : serverProblem(server);
  const warning = server?.database?.warning || '';
  const port = server?.port;
  const local = port ? `http://127.0.0.1:${port}` : '';
  const lan = port && server?.lan_ip ? `http://${server.lan_ip}:${port}` : '';
  const busy = isTransitional(phase) && phase !== 'connecting';
  const stopLike = action === 'stop' || phase === 'stopping';
  return (
    <Card title={t('dash.server')}>
      <div class="server-card">
        <div>
          <div class="server-title"><StatusDot tone={PHASE_TONE[phase]} />{t(PHASE_TITLE[phase])}</div>
          {sub ? <p class="muted small mt-2">{t(sub)}</p> : null}
        </div>
        <Button
          variant={stopLike ? 'danger' : 'primary'}
          icon={<IconPower size={15} />}
          loading={busy}
          disabled={action === null}
          onClick={() => { if (action) void runPowerAction(action, t); }}
        >
          {t(stopLike ? 'dash.stop' : 'dash.start')}
        </Button>
      </div>
      {problem ? <div class="mt-3"><Banner tone="danger">{problem}</Banner></div> : null}
      {warning && !problem ? <div class="mt-3"><Banner tone="warn">{warning}</Banner></div> : null}
      <div class="mt-3">
        {server ? (
          <KeyValue>
            <KV label={t('dash.local')} mono copy={local || undefined}>{local || '—'}</KV>
            <KV label={t('dash.network')} mono copy={lan || undefined}>{lan || '—'}</KV>
            <KV label={t('dash.uptime')}><Uptime startedAt={server.started_at} running={phase === 'running'} /></KV>
          </KeyValue>
        ) : <Skeleton lines={3} />}
      </div>
    </Card>
  );
}

function SignInCard() {
  const t = useT();
  const q = useAdminCredentials();
  const [show, setShow] = useState(false);
  return (
    <Card title={t('dash.signin')}>
      <QueryBoundary q={q} skeleton={2}>
        {(d) => (
          <KeyValue>
            <KV label={t('dash.adminEmail')} mono copy={d.email || undefined}>{d.email || '—'}</KV>
            <KV label={t('dash.password')} mono>
              {d.password ? (show ? d.password : '••••••••') : '—'}
              {d.password ? (
                <>
                  <IconButton label={t(show ? 'dash.hidePwd' : 'dash.showPwd')} onClick={() => setShow(!show)} aria-pressed={show}>
                    <IconEye size={14} />
                  </IconButton>
                  <CopyButton text={d.password} label={t('dash.password')} />
                </>
              ) : null}
            </KV>
          </KeyValue>
        )}
      </QueryBoundary>
    </Card>
  );
}

function SyncTile() {
  const t = useT();
  const q = useSyncStatus();
  const busy = useSignal(syncBusySignal);
  const sync = q.data?.sync;
  const pill = deriveSyncPill(sync, busy);
  return (
    <Card class="tile" title={t('dash.cloudSync')} actions={sync ? <Badge tone={pill.tone}>{t(pill.label)}</Badge> : null}>
      <QueryBoundary q={q}>
        {() => (
          <>
            <KeyValue>
              <KV label={t('dash.pending')} mono>{pill.pending}</KV>
              <KV label={t('dash.lastPush')}><RelativeTime iso={sync?.last_sync} /></KV>
              <KV label={t('dash.lastPull')}><RelativeTime iso={sync?.last_pull_at} /></KV>
            </KeyValue>
            {pill.replayPending ? <p class="small text-warn">{t('sync.replayPending')}</p> : null}
            {sync?.last_pull_error ? <p class="small text-danger wrap">{sync.last_pull_error}</p> : null}
            {sync?.last_error && sync.last_error !== sync.last_pull_error ? <p class="small text-danger wrap">{sync.last_error}</p> : null}
          </>
        )}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" icon={<IconRefresh size={14} />} loading={busy} onClick={() => void runSyncNow(t)}>{t('dash.syncNow')}</Button>
      </div>
    </Card>
  );
}

function HeartbeatTile() {
  const t = useT();
  const q = useLicenseStatus();
  const { server } = useBackend();
  const [busy, setBusy] = useState(false);
  const lic = q.data?.license;
  const registered = lic?.status === 'ACTIVE';
  const worker = server?.workers?.heartbeat || {};
  const statusError = lic?.status === 'SUSPENDED' || lic?.status === 'EXPIRED';
  const lastError = worker.last_error || (statusError ? lic?.last_message || '' : '');
  const healthy = registered && !!worker.alive && !worker.last_error;
  const beat = async () => {
    setBusy(true);
    try {
      const r = await api('license_heartbeat_now');
      toast(isFailure(r) ? errorText(r, t('dash.heartbeatFailed')) : t('dash.heartbeatOk'), isFailure(r) ? 'danger' : 'ok');
    } finally {
      setBusy(false);
      store.invalidate(['license_status', 'server_status']);
    }
  };
  return (
    <Card class="tile" title={t('dash.heartbeat')} actions={lic ? <Badge tone={healthy ? 'ok' : 'muted'}>{t(healthy ? 'common.online' : 'common.offline')}</Badge> : null}>
      <QueryBoundary q={q}>
        {() => (
          <KeyValue>
            <KV label={t('dash.controlCenter')} mono>{hostFromUrl(lic?.control_center_url) || '—'}</KV>
            <KV label={t('dash.lastBeat')}><RelativeTime iso={lic?.last_heartbeat_at} /></KV>
            <KV label={t('dash.nextBeat')} mono dim={!worker.alive}>{worker.next_run_in_s != null ? `${worker.next_run_in_s}s` : '—'}</KV>
            <KV label={t('dash.lastError')} dim={!lastError}>{lastError || t('common.none')}</KV>
          </KeyValue>
        )}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" icon={<IconRefresh size={14} />} loading={busy} disabled={!registered} onClick={() => void beat()}>{t('dash.heartbeatNow')}</Button>
      </div>
    </Card>
  );
}

function LicenseTile() {
  const t = useT();
  const q = useLicenseStatus();
  const lic = q.data?.license;
  const registered = lic?.status === 'ACTIVE';
  const days = lic ? (lic.days_remaining ?? daysUntil(lic.expires_at, Date.now())) : null;
  return (
    <Card class="tile" title={t('dash.license')} actions={lic ? <Badge tone={registered ? 'ok' : 'warn'}>{t(registered ? 'common.active' : 'common.unregistered')}</Badge> : null}>
      <QueryBoundary q={q}>
        {() => registered ? (
          <>
            <KeyValue>
              <KV label={t('dash.org')}>{lic?.org_name || '—'}</KV>
              <KV label={t('dash.plan')}>{lic?.plan || '—'}</KV>
              <KV label={t('dash.expires')} mono>{fmtDate(lic?.expires_at)}</KV>
            </KeyValue>
            {days !== null ? (
              <>
                <Meter pct={daysLeftPct(days)} label={t('dash.daysLeft')} />
                <span class="small muted">{days} {t('dash.daysLeft')}</span>
              </>
            ) : null}
          </>
        ) : <p class="muted small">{t('lic.sub')}</p>}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" variant={registered || !lic ? 'secondary' : 'primary'} onClick={() => navigate('license')}>
          {t(registered || !lic ? 'common.manage' : 'dash.registerNow')}
        </Button>
      </div>
    </Card>
  );
}

function FiscalTile() {
  const t = useT();
  const q = useFiscalStatus();
  return (
    <Card class="tile" title={t('nav.fiscal')}>
      <QueryBoundary q={q}>
        {(d) => {
          const f = d.fiscal || {};
          const mode = FIS_MODE[f.mode || 'off'];
          return (
            <KeyValue>
              <KV label={t('dash.mode')}>{mode ? t(mode) : f.mode}</KV>
              <KV label={t('dash.provider')} mono>{f.provider || '—'}</KV>
              <KV label={t('dash.confirmedFailed')} mono>{`${f.confirmed ?? 0} / ${f.failed ?? 0}`}</KV>
            </KeyValue>
          );
        }}
      </QueryBoundary>
      <div class="tile-foot">
        <Button size="sm" onClick={() => navigate('fiscal')}>{t('common.manage')}</Button>
      </div>
    </Card>
  );
}

function UpdatesTile() {
  const t = useT();
  const q = useUpdateStatus();
  const caps = capabilities();
  const [busy, setBusy] = useState(false);
  const d = q.data;
  const newer = !!(d?.available && d.available !== d.version);
  const restart = async () => {
    setBusy(true);
    const r = await restartToUpdate();
    setBusy(false);
    if (isFailure(r)) toast(errorText(r, t('upd.restartFailed')), 'danger');
  };
  return (
    <Card
      class="tile" title={t('nav.updates')}
      actions={d ? <Badge tone={d.pending ? 'warn' : newer ? 'info' : 'ok'}>{t(d.pending ? 'upd.pending' : newer ? 'upd.newAvailable' : 'upd.upToDate')}</Badge> : null}
    >
      <QueryBoundary q={q}>
        {(u) => (
          <KeyValue>
            <KV label={t('upd.version')} mono>{u.version ? `v${u.version}` : '—'}</KV>
            <KV label={t('upd.mode')}>{t(!u.frozen ? 'upd.dev' : u.enabled === false ? 'upd.disabledMode' : 'upd.installed')}</KV>
          </KeyValue>
        )}
      </QueryBoundary>
      <div class="tile-foot">
        {caps.restartToUpdate && d?.pending ? (
          <Button size="sm" variant="primary" loading={busy} onClick={() => void restart()}>{t('upd.restart')}</Button>
        ) : null}
        <Button size="sm" onClick={() => navigate('updates')}>{t('common.manage')}</Button>
      </div>
    </Card>
  );
}
