const pad = (n: number) => String(n).padStart(2, '0');

export function fmtUptime(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const days = Math.floor(s / 86400);
  const hms = `${pad(Math.floor((s % 86400) / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  return days > 0 ? `${days}d ${hms}` : hms;
}

export function parseTime(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function uptimeSeconds(startedAt: string | null | undefined, now: number): number | null {
  const start = parseTime(startedAt);
  return start === null ? null : Math.max(0, Math.floor((now - start) / 1000));
}

export function fmtClock(iso: string | null | undefined): string {
  const ms = parseTime(iso);
  if (ms === null) return '—';
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

export function fmtDateTime(iso: string | null | undefined): string {
  const ms = parseTime(iso);
  if (ms === null) return iso ? String(iso) : '—';
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fmtDate(iso: string | null | undefined): string {
  return iso ? String(iso).slice(0, 10) : '—';
}

export function daysUntil(iso: string | null | undefined, now: number): number | null {
  const ms = parseTime(iso);
  if (ms === null) return null;
  return Math.max(0, Math.round((ms - now) / 86_400_000));
}

export function daysLeftPct(days: number | null): number {
  if (days === null) return 0;
  return Math.max(0, Math.min(100, Math.round((days / 365) * 100)));
}

export function fmtBytes(value: unknown): string {
  const n = Math.max(0, Number(value) || 0);
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${Math.round(n)} B`;
}

export function fmtPrice(value: unknown): string | null {
  if (value == null || value === '') return null;
  const n = typeof value === 'number' ? value : Number(String(value).replace(/[^\d.]/g, ''));
  if (!Number.isFinite(n) || n <= 0) return String(value);
  return String(Math.round(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function hostFromUrl(url: string | null | undefined): string {
  if (!url) return '';
  return String(url).replace(/^https?:\/\//, '').replace(/\/.*$/, '');
}

export type RelativeUnit = 'now' | 'min' | 'hour' | 'day';

export function relativeParts(iso: string | null | undefined, now: number): { unit: RelativeUnit; n: number } | null {
  const ms = parseTime(iso);
  if (ms === null) return null;
  const seconds = Math.max(0, Math.round((now - ms) / 1000));
  if (seconds < 60) return { unit: 'now', n: 0 };
  if (seconds < 3600) return { unit: 'min', n: Math.floor(seconds / 60) };
  if (seconds < 86_400) return { unit: 'hour', n: Math.floor(seconds / 3600) };
  return { unit: 'day', n: Math.floor(seconds / 86_400) };
}

export type LogLevelClass = 'error' | 'warning' | 'info' | 'debug';

export function logLevelClass(level: string | null | undefined): LogLevelClass {
  const l = String(level || '').toUpperCase();
  if (l === 'ERROR' || l === 'CRITICAL') return 'error';
  if (l === 'WARNING') return 'warning';
  if (l === 'DEBUG') return 'debug';
  return 'info';
}

/** "2026-06-12 14:32:01,123" -> "2026-06-12 14:32:01". */
export function logTs(ts: string | null | undefined): string {
  return String(ts || '').replace(/[.,]\d+$/, '');
}
