import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../bridge/methods';
import type { LocalAuditStatus } from '../bridge/types';
import { IconCheck, IconSend } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { RelativeTime } from '../components/time';
import { toast } from '../components/Toasts';
import { Badge, Button, Card, Field, KeyValue, KV, Segmented, Switch } from '../components/ui';
import { POLL } from '../data/queries';
import { store } from '../data/store';
import { useMethodQuery } from '../data/useQuery';
import { useT } from '../i18n';
import type { Tone } from '../lib/sync';
import { useUnsavedGuard } from '../router/router';

const KEY = 'local_telegram_audit_status';

interface AuditForm {
  enabled: boolean;
  order_recorded: boolean;
  order_paid: boolean;
  shift_reports: boolean;
  report_format: string;
  bot_token: string;
  chat_ids: string;
}

const EMPTY_FORM: AuditForm = {
  enabled: false, order_recorded: true, order_paid: true, shift_reports: true,
  report_format: 'TXT', bot_token: '', chat_ids: '',
};

const FORMAT_OPTIONS = [
  { value: 'TXT', label: 'TXT' },
  { value: 'MD', label: 'Markdown' },
];

function formFromStatus(r: LocalAuditStatus): AuditForm {
  return {
    enabled: !!r.enabled,
    order_recorded: r.order_recorded !== false,
    order_paid: r.order_paid !== false,
    shift_reports: r.shift_reports !== false,
    report_format: r.report_format || 'TXT',
    chat_ids: (r.chat_ids || []).join(', '),
    bot_token: '',
  };
}

/** Module-level so it never remounts (the legacy screen redefined it every render). */
function ToggleRow({ title, detail, checked, onChange }: { title: string; detail: string; checked: boolean; onChange: (on: boolean) => void }) {
  return (
    <div class="toggle-row">
      <div>
        <div>{title}</div>
        <div class="small muted">{detail}</div>
      </div>
      <Switch checked={checked} label={title} onChange={onChange} />
    </div>
  );
}

export default function LocalAudit() {
  const t = useT();
  const q = useMethodQuery(KEY, { interval: POLL.localAudit, gate: 'django' });
  const [form, setForm] = useState<AuditForm>(EMPTY_FORM);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'' | 'save' | 'test'>('');
  const hydrated = useRef(false);
  useUnsavedGuard(dirty);

  // Hydration guard: the first status fills the form; later polls update the
  // status panel only and never overwrite what the operator is typing.
  const applyStatus = useCallback((r: LocalAuditStatus | undefined, forceHydrate: boolean) => {
    if (!r) return;
    if (hydrated.current && !forceHydrate) return;
    setForm(formFromStatus(r));
    hydrated.current = true;
    setDirty(false);
  }, []);

  useEffect(() => {
    applyStatus(q.data, false);
  }, [q.data, applyStatus]);

  const set = <K extends keyof AuditForm>(key: K, value: AuditForm[K]) => {
    setDirty(true);
    setForm((old) => ({ ...old, [key]: value }));
  };

  const save = async () => {
    if (busy) return;
    setBusy('save');
    const r = await api('save_local_telegram_audit', [form]);
    setBusy('');
    if (!isFailure(r)) {
      store.setData(KEY, () => r);
      applyStatus(r, true);
      toast(t('la.saved'), 'ok');
    } else {
      toast(errorText(r, t('common.saveFailed')), 'danger');
    }
  };

  const test = async () => {
    if (busy) return;
    setBusy('test');
    const r = await api('test_local_telegram_audit');
    setBusy('');
    if (!isFailure(r)) toast(t('la.testSent'), 'ok');
    else toast(r.failed?.[0]?.error || errorText(r, t('common.testFailed')), 'danger');
    store.invalidate([KEY]);
  };

  const status = q.data;
  const state = status?.configuration_state || 'disabled';
  const ready = state === 'ready';
  const stateTone: Tone = ready ? 'ok' : state === 'disabled' ? 'muted' : 'warn';
  const stateLabel = t(ready ? 'la.ready' : state === 'disabled' ? 'la.disabled' : 'la.setup');
  const canEdit = hydrated.current;

  return (
    <div class="page">
      <p class="page-sub">{t('la.sub')}</p>
      <div class="grid-2">
        <Card title={t('la.transport')} actions={status ? <Badge tone={stateTone}>{stateLabel}</Badge> : null}>
          <QueryBoundary q={q} skeleton={4}>
            {(s) => (
              <div class="stack">
                <Field label={t('la.token')} hint={t(s.token_configured ? 'la.tokenHintSet' : 'la.tokenHintEmpty')} htmlFor="la-token">
                  <input
                    id="la-token" class="input mono" type="password" autoComplete="new-password"
                    value={form.bot_token} placeholder={s.token_configured ? '••••••••' : '123456:…'}
                    onInput={(e) => set('bot_token', e.currentTarget.value)}
                  />
                </Field>
                <Field label={t('la.chats')} hint={t('la.chatsHint')} htmlFor="la-chats">
                  <textarea
                    id="la-chats" class="input mono" rows={3} value={form.chat_ids}
                    placeholder="-1001234567890, @owner_channel"
                    onInput={(e) => set('chat_ids', e.currentTarget.value)}
                  />
                </Field>
              </div>
            )}
          </QueryBoundary>
        </Card>

        <Card title={t('la.rules')}>
          <QueryBoundary q={q} skeleton={5}>
            {() => (
              <>
                <ToggleRow title={t('la.master')} detail={t('la.masterD')} checked={form.enabled} onChange={(on) => set('enabled', on)} />
                <ToggleRow title={t('la.recorded')} detail={t('la.recordedD')} checked={form.order_recorded} onChange={(on) => set('order_recorded', on)} />
                <ToggleRow title={t('la.paid')} detail={t('la.paidD')} checked={form.order_paid} onChange={(on) => set('order_paid', on)} />
                <ToggleRow title={t('la.shift')} detail={t('la.shiftD')} checked={form.shift_reports} onChange={(on) => set('shift_reports', on)} />
                <div class="field mt-3">
                  <span class="field-label">{t('la.format')}</span>
                  <Segmented options={FORMAT_OPTIONS} value={form.report_format} label={t('la.format')} onChange={(v) => set('report_format', v)} />
                </div>
              </>
            )}
          </QueryBoundary>
        </Card>

        <Card title={t('la.status')}>
          <QueryBoundary q={q} skeleton={5}>
            {(s) => (
              <>
                <KeyValue>
                  <KV label={t('la.pending')} mono>{s.pending_count || 0}</KV>
                  <KV label={t('la.retrying')} mono>{s.retrying_count || 0}</KV>
                  <KV label={t('la.worker')}>{t(s.worker_alive ? 'chip.running' : 'chip.stopped')}</KV>
                  <KV label={t('la.lastSent')}><RelativeTime iso={s.last_sent_at} fallback={t('la.never')} /></KV>
                  <KV label={t('la.direct')}>{t('la.directV')}</KV>
                </KeyValue>
                {s.last_error ? <p class="small text-danger wrap mt-2">{s.last_error}</p> : null}
                <div class="row mt-3">
                  <Button icon={<IconSend size={14} />} loading={busy === 'test'} disabled={!!busy || !ready} onClick={() => void test()}>
                    {t(busy === 'test' ? 'la.sending' : 'la.test')}
                  </Button>
                </div>
              </>
            )}
          </QueryBoundary>
        </Card>

        <Card title={t('la.privacy')}>
          <p class="muted">{t('la.privacyD')}</p>
        </Card>
      </div>

      <div class="savebar">
        <span class="grow small muted">{dirty ? t('common.unsavedTitle') : ' '}</span>
        <Button disabled={!dirty || !!busy} onClick={() => applyStatus(q.data, true)}>{t('common.discard')}</Button>
        <Button variant="primary" icon={<IconCheck size={14} />} loading={busy === 'save'} disabled={!canEdit || !dirty || !!busy} onClick={() => void save()}>
          {t('la.save')}
        </Button>
      </div>
    </div>
  );
}
