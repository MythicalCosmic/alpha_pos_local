import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { api, errorText, isFailure } from '../bridge/methods';
import { IconCheck, IconDownload, IconRefresh, IconTrash, IconUpload } from '../components/icons';
import { ConfirmModal } from '../components/Modal';
import { QueryBoundary } from '../components/QueryBoundary';
import { toast } from '../components/Toasts';
import { Button, Card, Field } from '../components/ui';
import { store } from '../data/store';
import { useMethodQuery } from '../data/useQuery';
import { useT, type I18nKey } from '../i18n';
import { parseConfigImport } from '../lib/config-import.mjs';
import { useUnsavedGuard } from '../router/router';

type FieldType = 'text' | 'secret' | readonly string[];

interface Section {
  id: string;
  title: I18nKey;
  hint?: I18nKey;
  fields: ReadonlyArray<readonly [string, FieldType]>;
}

// Mirrors desktop/config_store.CONFIG_FIELDS.
export const CFG_SECTIONS: readonly Section[] = [
  { id: 'general', title: 'cfg.general', fields: [['BRANCH_ID', 'text'], ['DEPLOYMENT_MODE', ['local', 'cloud']], ['PORT', 'text']] },
  { id: 'sync', title: 'cfg.sync', fields: [['CLOUD_SYNC_URL', 'text'], ['SYNC_ENABLED', ['True', 'False']], ['CLOUD_SYNC_TOKEN', 'secret']] },
  { id: 'support', title: 'cfg.support', hint: 'cfg.supportHint', fields: [['SUPPORT_TUNNEL_ENABLED', ['False', 'True']], ['SUPPORT_TUNNEL_HOST', 'text'], ['SUPPORT_TUNNEL_PORT', 'text'], ['SUPPORT_TUNNEL_USER', 'text'], ['SUPPORT_TUNNEL_REMOTE_DB_PORT', 'text'], ['SUPPORT_TUNNEL_REMOTE_API_PORT', 'text'], ['SUPPORT_TUNNEL_PRIVATE_KEY_B64', 'secret'], ['SUPPORT_TUNNEL_KNOWN_HOST', 'text']] },
  { id: 'licensing', title: 'cfg.licensing', fields: [['LICENSE_CONTROL_CENTER_URL', 'text'], ['ALPHA_POS_UPDATE_URL', 'text']] },
  { id: 'telegram', title: 'cfg.telegram', fields: [['ORDER_AUDIT_TELEGRAM_CHAT_IDS', 'text'], ['TELEGRAM_WEBHOOK_SECRET', 'secret']] },
  { id: 'fiscal', title: 'nav.fiscal', hint: 'cfg.fiscalHint', fields: [['FISCALIZATION_MODE', ['off', 'mock', 'sandbox', 'live']], ['FISCAL_PROVIDER', ['mock', 'multikassa']], ['FISCAL_TIN', 'text'], ['FISCAL_PROVIDER_URL', 'text'], ['FISCAL_VAT_PERCENT', 'text'], ['FISCAL_MERCHANT_ID', 'text'], ['FISCAL_SECRET', 'secret']] },
];

type Values = Record<string, string>;
const norm = (v: unknown) => (v == null ? '' : String(v));

export function changedKeys(initial: Values, draft: Values): string[] {
  const keys = new Set([...Object.keys(initial), ...Object.keys(draft)]);
  return [...keys].filter((k) => norm(initial[k]) !== norm(draft[k])).sort();
}

export default function Config() {
  const t = useT();
  const q = useMethodQuery('get_config');
  const [initial, setInitial] = useState<Values | null>(null);
  const [draft, setDraft] = useState<Values>({});
  const [busy, setBusy] = useState<'' | 'save' | 'import' | 'export' | 'flush' | 'reset'>('');
  const [confirm, setConfirm] = useState<'' | 'flush' | 'reset'>('');
  const fileRef = useRef<HTMLInputElement>(null);

  const secrets = useMemo(() => new Set(q.data?.secret_keys || []), [q.data]);
  const changed = useMemo(() => (initial ? changedKeys(initial, draft) : []), [initial, draft]);
  const dirty = changed.length > 0;
  useUnsavedGuard(dirty);

  const hydrate = (config: Values | undefined) => {
    const next = { ...(config || {}) };
    setInitial(next);
    setDraft(next);
  };

  // Hydrate once from the entry fetch; later refreshes never clobber a draft.
  useEffect(() => {
    if (initial === null && q.data?.config) hydrate(q.data.config);
  }, [q.data, initial]);

  const reload = async () => {
    const fresh = await store.fetch('get_config');
    if (!isFailure(fresh)) hydrate((fresh as { config?: Values }).config);
  };

  const set = (key: string, value: string) => setDraft((old) => ({ ...old, [key]: value }));

  const save = async () => {
    if (!initial || !dirty || busy) return;
    setBusy('save');
    // Only what the operator changed: untouched keys (staff Telegram recipients,
    // the support tunnel) must not be rewritten or restarted by an unrelated save.
    const r = await api('save_config', [Object.fromEntries(changed.map((key) => [key, norm(draft[key])]))]);
    setBusy('');
    if (isFailure(r)) {
      toast(errorText(r, t('common.saveFailed')), 'danger');
      return;
    }
    toast(t('cfg.savedToast') + (r.restart_required ? ` · ${t('cfg.restart')}` : ''), r.restart_required ? 'warn' : 'ok');
    await reload();
  };

  const exportEnv = async () => {
    setBusy('export');
    const r = await api('export_config');
    setBusy('');
    if (isFailure(r) || !r.config) {
      toast(errorText(r, t('cfg.exportFailed')), 'danger');
      return;
    }
    const config = r.config;
    const lines = ['# Alpha POS — exported configuration', ...Object.keys(config).sort().map((k) => `${k}=${norm(config[k])}`)];
    try {
      const blob = new Blob([lines.join('\n') + '\n'], { type: 'text/plain' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      // The backend suggests a .json name; this file is .env text.
      a.download = (r.filename || 'alpha-pos').replace(/\.json$/i, '') + '.env';
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    } catch {
      /* download unsupported in this shell */
    }
    toast(t('cfg.exported'), 'ok');
  };

  const onImportFile = (event: Event) => {
    const input = event.currentTarget as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const parsed = parseConfigImport(String(reader.result || ''), Object.keys(initial || {}));
      if (!parsed.ok) {
        toast(parsed.error || t('cfg.importFailed'), 'danger');
        return;
      }
      setBusy('import');
      const r = await api('import_config', [parsed.data]);
      setBusy('');
      if (isFailure(r)) {
        toast(errorText(r, t('cfg.importFailed')), 'danger');
        return;
      }
      toast(t('cfg.imported') + (r.restart_required ? ` · ${t('cfg.restart')}` : ''), 'ok');
      await reload();
    };
    reader.readAsText(file);
    input.value = '';
  };

  const destructive = async (kind: 'flush' | 'reset') => {
    setConfirm('');
    setBusy(kind);
    const r = kind === 'flush' ? await api('flush_database', [true]) : await api('factory_reset', [true]);
    setBusy('');
    if (isFailure(r)) toast(errorText(r, t('common.failed')), 'danger');
    else toast(kind === 'flush' ? t('cfg.flushed') : (r.message || t('cfg.flushed')), 'ok');
    store.invalidate(['server_status', 'admin_credentials']);
  };

  return (
    <div class="page">
      <div class="row-between">
        <p class="page-sub">{t('cfg.sub')}</p>
        <div class="row" style={{ marginBottom: '16px' }}>
          <input type="file" accept=".env,.json,text/plain,application/json" ref={fileRef} hidden onChange={onImportFile} aria-label={t('cfg.import')} />
          <Button icon={<IconUpload size={14} />} loading={busy === 'import'} disabled={!initial} onClick={() => fileRef.current?.click()}>{t('cfg.import')}</Button>
          <Button icon={<IconDownload size={14} />} loading={busy === 'export'} onClick={() => void exportEnv()}>{t('cfg.export')}</Button>
        </div>
      </div>

      <nav class="anchors" aria-label={t('cfg.sections')}>
        {CFG_SECTIONS.map((s) => (
          <Button key={s.id} size="sm" variant="ghost" onClick={() => document.getElementById(`cfg-${s.id}`)?.scrollIntoView({ block: 'start' })}>
            {t(s.title)}
          </Button>
        ))}
      </nav>

      <QueryBoundary q={q} skeleton={8}>
        {() => (
          <div class="stack">
            {CFG_SECTIONS.map((section) => (
              <Card key={section.id} id={`cfg-${section.id}`} title={t(section.title)}>
                {section.hint ? <p class="small muted" style={{ marginBottom: '12px' }}>{t(section.hint)}</p> : null}
                <div class="form-grid">
                  {section.fields.map(([key, type]) => {
                    const id = `cfg-f-${key}`;
                    if (Array.isArray(type)) {
                      const options = type as readonly string[];
                      return (
                        <Field key={key} label={key} htmlFor={id}>
                          <select id={id} class="input" value={draft[key] ?? options[0]} onChange={(e) => set(key, e.currentTarget.value)}>
                            {options.map((o) => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </Field>
                      );
                    }
                    const secret = type === 'secret' || secrets.has(key);
                    return (
                      <Field key={key} label={key} htmlFor={id}>
                        <input
                          id={id} class="input mono" type={secret ? 'password' : 'text'} autoComplete={secret ? 'new-password' : 'off'}
                          value={draft[key] ?? ''} placeholder={secret ? t('cfg.secretPh') : ''}
                          onInput={(e) => set(key, e.currentTarget.value)}
                        />
                      </Field>
                    );
                  })}
                </div>
              </Card>
            ))}

            <Card title={t('cfg.flushBtn')} tone="warn">
              <p class="muted" style={{ marginBottom: '12px' }}>{t('cfg.flushD')}</p>
              <Button variant="danger" icon={<IconRefresh size={14} />} loading={busy === 'flush'} disabled={!!busy} onClick={() => setConfirm('flush')}>{t('cfg.flushBtn')}</Button>
            </Card>
            <Card title={t('cfg.dangerT')} tone="danger">
              <p class="muted" style={{ marginBottom: '12px' }}>{t('cfg.dangerD')}</p>
              <Button variant="danger" icon={<IconTrash size={14} />} loading={busy === 'reset'} disabled={!!busy} onClick={() => setConfirm('reset')}>{t('cfg.dangerBtn')}</Button>
            </Card>
          </div>
        )}
      </QueryBoundary>

      <div class="savebar">
        <span class="grow small muted">{dirty ? t('common.changed', { n: changed.length }) : ' '}</span>
        <Button disabled={!dirty || !!busy} onClick={() => initial && setDraft({ ...initial })}>{t('common.discard')}</Button>
        <Button variant="primary" icon={<IconCheck size={14} />} loading={busy === 'save'} disabled={!initial || !dirty || !!busy} onClick={() => void save()}>
          {t('cfg.saveBtn')}
        </Button>
      </div>

      <ConfirmModal
        open={confirm === 'flush'} title={t('cfg.flushBtn')} body={t('cfg.flushConfirm')} danger
        confirmLabel={t('cfg.flushBtn')} cancelLabel={t('common.cancel')}
        onConfirm={() => void destructive('flush')} onCancel={() => setConfirm('')}
      />
      <ConfirmModal
        open={confirm === 'reset'} title={t('cfg.dangerT')} body={t('cfg.dangerConfirm')} danger
        confirmLabel={t('cfg.dangerBtn')} cancelLabel={t('common.cancel')}
        onConfirm={() => void destructive('reset')} onCancel={() => setConfirm('')}
      />
    </div>
  );
}
