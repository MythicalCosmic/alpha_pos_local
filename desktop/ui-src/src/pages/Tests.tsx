import { useEffect, useRef, useState } from 'preact/hooks';
import { api, errorText, isFailure, type MethodName } from '../bridge/methods';
import { IconCheck, IconDownload, IconFlask, IconRefresh, IconWarn } from '../components/icons';
import { ConfirmModal } from '../components/Modal';
import { QueryBoundary } from '../components/QueryBoundary';
import { toast } from '../components/Toasts';
import { Badge, Button, Card, KeyValue, KV, Spinner } from '../components/ui';
import { store } from '../data/store';
import { useMethodQuery } from '../data/useQuery';
import { useT, type I18nKey } from '../i18n';

interface TestDef {
  id: string;
  name: I18nKey;
  desc: I18nKey;
  method: MethodName;
}

const LOCAL_TESTS: readonly TestDef[] = [
  { id: 't1', name: 'tests.t1', desc: 'tests.t1d', method: 'test_server_connection' },
  { id: 't2', name: 'tests.t2', desc: 'tests.t2d', method: 'send_mock_sync' },
  { id: 't3', name: 'tests.t3', desc: 'tests.t3d', method: 'fetch_mock_sync' },
  { id: 't4', name: 'tests.t4', desc: 'tests.t4d', method: 'telegram_test' },
  { id: 't5', name: 'tests.t5', desc: 'tests.t5d', method: 'send_fake_notification' },
  { id: 't6', name: 'nav.fiscal', desc: 'tests.t6d', method: 'fiscal_test' },
];
const CLOUD_TESTS: readonly TestDef[] = [
  { id: 't7', name: 'tests.t7', desc: 'tests.t7d', method: 'cloud_test_connection' },
  { id: 't8', name: 'tests.t8', desc: 'tests.t8d', method: 'cloud_sync_now' },
  { id: 't9', name: 'tests.t9', desc: 'tests.t9d', method: 'cloud_pull' },
];
const ALL_TESTS = [...LOCAL_TESTS, ...CLOUD_TESTS];

type Result = 'running' | { ok: boolean; ms: number; error?: string };

function TestTile({ test, result, onRun, disabled }: { test: TestDef; result: Result | undefined; onRun: () => void; disabled: boolean }) {
  const t = useT();
  const running = result === 'running';
  const done = result && result !== 'running' ? result : null;
  return (
    <Card class="tile" title={t(test.name)} tone={done && !done.ok ? 'danger' : undefined}>
      <p class="small muted">{t(test.desc)}</p>
      {done?.error ? <p class="small text-danger wrap">{done.error}</p> : null}
      <div class="tile-foot">
        <span class="row small grow" style={{ flex: '1 1 auto' }}>
          {running ? <Spinner /> : null}
          {done ? (
            <span class={done.ok ? 'text-ok row' : 'text-danger row'}>
              {done.ok ? <IconCheck size={13} /> : <IconWarn size={13} />}
              {done.ok ? 'OK' : t('tests.failed')} · {done.ms} ms
            </span>
          ) : null}
        </span>
        <Button size="sm" onClick={onRun} disabled={running || disabled}>{t('common.run')}</Button>
      </div>
    </Card>
  );
}

export default function Tests() {
  const t = useT();
  const [results, setResults] = useState<Record<string, Result>>({});
  const [runningAll, setRunningAll] = useState(false);
  const alive = useRef(true);
  const runToken = useRef(0);

  // Leaving the page cancels an in-progress "Run all": no further calls start.
  useEffect(() => () => {
    alive.current = false;
    runToken.current += 1;
  }, []);

  const run = async (test: TestDef) => {
    if (!alive.current) return;
    setResults((r) => ({ ...r, [test.id]: 'running' }));
    const started = performance.now();
    const res = await api(test.method);
    if (!alive.current) return;
    const ms = Math.round(performance.now() - started);
    const ok = !isFailure(res);
    setResults((r) => ({ ...r, [test.id]: { ok, ms, error: ok ? undefined : errorText(res, '') || undefined } }));
  };

  const runAll = async () => {
    const token = ++runToken.current;
    setRunningAll(true);
    for (const test of ALL_TESTS) {
      if (!alive.current || token !== runToken.current) return;
      await run(test);
    }
    if (alive.current && token === runToken.current) setRunningAll(false);
  };

  const passed = ALL_TESTS.filter((x) => {
    const r = results[x.id];
    return r && r !== 'running' && r.ok;
  }).length;

  return (
    <div class="page">
      <div class="row-between">
        <p class="page-sub">{t('tests.sub')}</p>
        <div class="row" style={{ marginBottom: '16px' }}>
          {passed > 0 ? <span class="small text-ok mono">{passed} / {ALL_TESTS.length} {t('tests.passed')}</span> : null}
          <Button variant="primary" icon={<IconFlask size={14} />} loading={runningAll} onClick={() => void runAll()}>{t('common.runAll')}</Button>
        </div>
      </div>

      <h2 class="section-title">{t('tests.local')}</h2>
      <div class="test-grid">
        {LOCAL_TESTS.map((x) => <TestTile key={x.id} test={x} result={results[x.id]} disabled={runningAll} onRun={() => void run(x)} />)}
      </div>

      <h2 class="section-title">{t('tests.cloud')}</h2>
      <p class="page-sub">{t('tests.cloudHint')}</p>
      <div class="test-grid">
        {CLOUD_TESTS.map((x) => <TestTile key={x.id} test={x} result={results[x.id]} disabled={runningAll} onRun={() => void run(x)} />)}
      </div>

      <RecoveryPanel />
    </div>
  );
}

function RecoveryPanel() {
  const t = useT();
  const q = useMethodQuery('cloud_dead_letters', { gate: 'django' });
  const [busy, setBusy] = useState<'' | 'retry' | 'pull'>('');
  const [confirmPull, setConfirmPull] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const total = q.data?.total ?? null;

  const retry = async () => {
    setBusy('retry');
    const r = await api('cloud_resync_failed');
    if (alive.current) setBusy('');
    toast(!isFailure(r) ? t('tests.retryDone', { n: r.requeued || 0 }) : errorText(r, t('common.failed')), isFailure(r) ? 'danger' : 'ok');
    store.invalidate(['cloud_dead_letters', 'sync_status']);
  };

  const forcePull = async () => {
    setConfirmPull(false);
    setBusy('pull');
    const r = await api('cloud_force_pull');
    if (alive.current) setBusy('');
    const replayQueued = !!(r && r.replay_requested && r.will_retry);
    toast(
      r && r.ok
        ? t('tests.forcePullDone')
        : replayQueued
          ? t('tests.forcePullQueued')
          : (r && r.error) || t('tests.forcePullQueued'),
      r && r.ok ? 'ok' : replayQueued ? 'warn' : 'danger',
    );
    store.invalidate(['cloud_dead_letters', 'sync_status']);
  };

  return (
    <Card class="mt-4" title={t('tests.recovery')} tone={total ? 'warn' : undefined}>
      <p class="small muted" style={{ marginBottom: '12px' }}>{t('tests.recoveryHint')}</p>
      <QueryBoundary q={q} skeleton={2}>
        {(d) => (
          <KeyValue>
            <KV label={t('tests.stuckLabel')}><Badge tone={d.total ? 'warn' : 'ok'}>{d.total || 0}</Badge></KV>
            {Object.entries(d.by_model || {}).map(([model, n]) => <KV key={model} label={model} mono dim>{n}</KV>)}
          </KeyValue>
        )}
      </QueryBoundary>
      <div class="row mt-3">
        {total === 0 ? <span class="small text-ok">{t('tests.stuckNone')}</span> : null}
        {total ? <span class="small muted">{t('tests.stuckSome')}</span> : null}
        <Button variant={total ? 'primary' : 'secondary'} icon={<IconRefresh size={14} />} loading={busy === 'retry'} disabled={!!busy || !total} onClick={() => void retry()}>
          {t('tests.retryStuck')}
        </Button>
        <Button icon={<IconDownload size={14} />} loading={busy === 'pull'} disabled={!!busy} onClick={() => setConfirmPull(true)}>
          {t('tests.forcePull')}
        </Button>
      </div>
      <ConfirmModal
        open={confirmPull} title={t('tests.forcePull')} body={t('tests.forcePullConfirm')}
        confirmLabel={t('tests.forcePull')} cancelLabel={t('common.cancel')}
        onConfirm={() => void forcePull()} onCancel={() => setConfirmPull(false)}
      />
    </Card>
  );
}
