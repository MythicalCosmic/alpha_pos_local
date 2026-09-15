import type { ComponentChildren } from 'preact';
import { useBackend, useOrderAuditStatus, useSyncStatus, useTunnelStatus, useUpdateStatus } from '../data/queries';
import { syncBusySignal } from '../data/actions';
import { useSignal } from '../data/signal';
import type { BackendPhase } from '../data/backendPhase';
import { useT, type I18nKey } from '../i18n';
import { deriveSyncPill, type Tone } from '../lib/sync';
import { hrefFor, navigate, type RouteId } from '../router/router';
import { ROUTE_MAP } from '../router/routes';
import { StatusDot } from '../components/ui';

const PHASE_CHIP: Record<BackendPhase, { key: I18nKey; tone: Tone }> = {
  connecting: { key: 'chip.connecting', tone: 'muted' },
  unreachable: { key: 'chip.unreachable', tone: 'danger' },
  booting: { key: 'chip.booting', tone: 'warn' },
  starting: { key: 'chip.starting', tone: 'warn' },
  stopping: { key: 'chip.stopping', tone: 'warn' },
  running: { key: 'chip.running', tone: 'ok' },
  error: { key: 'chip.error', tone: 'danger' },
  stopped: { key: 'chip.stopped', tone: 'muted' },
};

function Chip({ to, tone, label, name, title }: { to: RouteId; tone: Tone; label: string; name: string; title?: string }) {
  return (
    <a
      class="chip" href={hrefFor(to)} aria-label={`${name}: ${label}`} title={title || `${name}: ${label}`}
      onClick={(e) => { e.preventDefault(); navigate(to); }}
    >
      <StatusDot tone={tone} />
      <span class="chip-label">{label}</span>
    </a>
  );
}

function BackendChip() {
  const t = useT();
  const { phase } = useBackend();
  const chip = PHASE_CHIP[phase];
  return <Chip to="dashboard" tone={chip.tone} label={t(chip.key)} name={t('chip.serverLabel')} />;
}

function SyncChip() {
  const t = useT();
  const q = useSyncStatus();
  const busy = useSignal(syncBusySignal);
  if (!q.data?.sync && !busy) return null;
  const pill = deriveSyncPill(q.data?.sync, busy);
  const label = t(pill.label) + (pill.pending ? ` · ${pill.pending}` : '');
  const title = [t(pill.label), pill.pending ? `${pill.pending} ${t('sync.pending')}` : '', ...pill.details].filter(Boolean).join(' · ');
  return <Chip to="dashboard" tone={pill.tone} label={label} name={t('dash.cloudSync')} title={title} />;
}

function TunnelChip() {
  const t = useT();
  const { data } = useTunnelStatus();
  if (!data || data.ok === false) return null;
  const tone: Tone = data.ready ? 'ok' : data.enabled ? 'warn' : 'muted';
  const label = t(data.ready ? 'obs.dbReadyShort' : data.enabled ? 'obs.dbWaitingShort' : 'obs.dbOffShort');
  return <Chip to="dashboard" tone={tone} label={label} name={t('chip.tunnelLabel')} title={data.last_error || data.last_probe_error || undefined} />;
}

function AuditChip() {
  const t = useT();
  const { data } = useOrderAuditStatus();
  if (!data || data.ok === false) return null;
  const error = data.delivery_state === 'error' || data.delivery_state === 'configuration_required';
  const active = data.enabled !== false && data.auto_send !== false;
  const tone: Tone = error ? 'danger' : active ? 'ok' : 'muted';
  const label = t(active ? 'obs.telegramOnShort' : 'obs.telegramOffShort');
  return <Chip to="dashboard" tone={tone} label={label} name={t('chip.auditLabel')} title={data.last_auto_send_error || data.last_error || undefined} />;
}

function UpdateChip() {
  const t = useT();
  const { data } = useUpdateStatus();
  if (!data || data.ok === false) return null;
  const available = !!(data.available && data.available !== data.version);
  if (!data.pending && !available && !data.active) return null;
  return <Chip to="updates" tone="info" label={t('chip.update')} name={t('nav.updates')} />;
}

export function TopBar({ route }: { route: RouteId }) {
  const t = useT();
  return (
    <header class="topbar">
      <h1>{t(ROUTE_MAP[route].titleKey)}</h1>
      <Chips>
        <BackendChip />
        <SyncChip />
        <TunnelChip />
        <AuditChip />
        <UpdateChip />
      </Chips>
    </header>
  );
}

function Chips({ children }: { children: ComponentChildren }) {
  const t = useT();
  return <nav class="chips" aria-label={t('common.status')}>{children}</nav>;
}
