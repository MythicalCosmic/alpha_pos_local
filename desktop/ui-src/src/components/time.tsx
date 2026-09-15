import { useEffect, useState } from 'preact/hooks';
import { useT } from '../i18n';
import { fmtDateTime, fmtUptime, relativeParts, uptimeSeconds } from '../lib/format';

/** Current time, ticking every `intervalMs` only while active and the window is visible. */
export function useNow(intervalMs: number, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    let id: ReturnType<typeof setInterval> | undefined;
    const stop = () => {
      if (id !== undefined) clearInterval(id);
      id = undefined;
    };
    const start = () => {
      stop();
      if (document.visibilityState === 'hidden') return;
      setNow(Date.now());
      id = setInterval(() => setNow(Date.now()), intervalMs);
    };
    start();
    document.addEventListener('visibilitychange', start);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', start);
    };
  }, [intervalMs, active]);
  return now;
}

/** Leaf that owns its 1 s tick, so nothing else re-renders every second. */
export function Uptime({ startedAt, running }: { startedAt: string | null | undefined; running: boolean }) {
  const active = running && !!startedAt;
  const now = useNow(1000, active);
  const seconds = active ? uptimeSeconds(startedAt, now) : null;
  return <span class="mono" data-uptime="">{seconds === null ? '—' : fmtUptime(seconds)}</span>;
}

export function RelativeTime({ iso, fallback = '—' }: { iso: string | null | undefined; fallback?: string }) {
  const t = useT();
  const now = useNow(30_000, !!iso);
  const parts = relativeParts(iso, now);
  if (!iso || !parts) return <span class="muted">{iso ? String(iso) : fallback}</span>;
  const label = parts.unit === 'now'
    ? t('common.justNow')
    : t(parts.unit === 'min' ? 'time.minAgo' : parts.unit === 'hour' ? 'time.hourAgo' : 'time.dayAgo', { n: parts.n });
  return <time dateTime={iso} title={fmtDateTime(iso)}>{label}</time>;
}
