import { useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../bridge/methods';
import { IconReceipt } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { toast } from '../components/Toasts';
import { Badge, Button, Card, KeyValue, KV, Segmented } from '../components/ui';
import { useFiscalStatus } from '../data/queries';
import { store } from '../data/store';
import { useT } from '../i18n';

const KEY = 'fiscal_status';
type Mode = 'off' | 'mock' | 'sandbox' | 'live';

export default function Fiscal() {
  const t = useT();
  const q = useFiscalStatus();
  const [testing, setTesting] = useState(false);
  const [switching, setSwitching] = useState(false);
  const fiscal = q.data?.fiscal;

  const modes = [
    { value: 'off' as Mode, label: t('fis.off') },
    { value: 'mock' as Mode, label: t('fis.mock') },
    { value: 'sandbox' as Mode, label: t('fis.sandbox') },
    { value: 'live' as Mode, label: t('fis.live') },
  ];

  // Optimistic: flip immediately, roll back with a toast if the backend refuses.
  const setMode = async (mode: Mode) => {
    const previous = store.getState(KEY).data;
    store.setData(KEY, (d) => ({ ...(d || {}), fiscal: { ...((d?.fiscal as object) || {}), mode } }));
    setSwitching(true);
    const r = await api('fiscal_set_mode', [mode]);
    setSwitching(false);
    if (isFailure(r)) {
      store.setData(KEY, () => previous);
      toast(errorText(r, t('fis.modeFailed')), 'danger');
    }
    store.invalidate([KEY]);
  };

  const runTest = async () => {
    setTesting(true);
    const r = await api('fiscal_test');
    setTesting(false);
    toast(!isFailure(r) ? t('fis.testOk') : errorText(r, t('common.testFailed')), isFailure(r) ? 'danger' : 'ok');
    store.invalidate([KEY]);
  };

  return (
    <div class="page">
      <p class="page-sub">{t('fis.sub')}</p>
      <div class="grid-2">
        <Card title={t('dash.mode')}>
          <QueryBoundary q={q} skeleton={2}>
            {() => (
              <Segmented options={modes} value={(fiscal?.mode as Mode) || 'off'} label={t('dash.mode')} disabled={switching} onChange={(m) => void setMode(m)} />
            )}
          </QueryBoundary>
          <div class="mt-4">
            <Button variant="primary" icon={<IconReceipt size={14} />} loading={testing} onClick={() => void runTest()}>{t('fis.runTest')}</Button>
          </div>
        </Card>
        <Card title={t('common.status')}>
          <QueryBoundary q={q} skeleton={3}>
            {(d) => {
              const f = d.fiscal || {};
              const enabled = (f.mode || 'off') !== 'off';
              return (
                <KeyValue>
                  <KV label={t('fis.enabled')}><Badge tone={enabled ? 'ok' : 'muted'}>{t(enabled ? 'common.yes' : 'common.no')}</Badge></KV>
                  <KV label={t('dash.provider')} mono>{f.provider || '—'}</KV>
                  <KV label={t('dash.confirmedFailed')} mono>{`${f.confirmed ?? 0} / ${f.failed ?? 0}`}</KV>
                </KeyValue>
              );
            }}
          </QueryBoundary>
        </Card>
      </div>
    </div>
  );
}
