import { describe, expect, it } from 'vitest';
import { parseConfigImport } from '../../src/lib/config-import.mjs';
import {
  daysLeftPct, daysUntil, fmtBytes, fmtClock, fmtDate, fmtPrice, fmtUptime, hostFromUrl,
  logLevelClass, logTs, relativeParts, uptimeSeconds,
} from '../../src/lib/format';
import { FALLBACK_PLANS, findCurrentPlan, normalizePlans } from '../../src/lib/plans';
import { DEFAULT_PREFS, migratePrefs, readCachedPrefs } from '../../src/lib/prefs';
import { deriveSyncPill, isReplayPending, shiftCloseState } from '../../src/lib/sync';
import { changedKeys } from '../../src/pages/Config';
import { filterLogs } from '../../src/pages/Logs';

describe('format helpers', () => {
  it('formats uptime from seconds and started_at', () => {
    expect(fmtUptime(0)).toBe('00:00:00');
    expect(fmtUptime(3725)).toBe('01:02:05');
    expect(fmtUptime(90_061)).toBe('1d 01:01:01');
    const now = Date.parse('2026-09-16T10:00:10Z');
    expect(uptimeSeconds('2026-09-16T10:00:00Z', now)).toBe(10);
    expect(uptimeSeconds(null, now)).toBeNull();
    expect(uptimeSeconds('garbage', now)).toBeNull();
  });

  it('computes days left and meter percentage', () => {
    const now = Date.parse('2026-01-01T00:00:00Z');
    expect(daysUntil('2026-01-11T00:00:00Z', now)).toBe(10);
    expect(daysUntil('2025-01-01T00:00:00Z', now)).toBe(0);
    expect(daysUntil(null, now)).toBeNull();
    expect(daysLeftPct(365)).toBe(100);
    expect(daysLeftPct(73)).toBe(20);
    expect(daysLeftPct(null)).toBe(0);
  });

  it('formats bytes, prices, hosts, dates', () => {
    expect(fmtBytes(0)).toBe('0 B');
    expect(fmtBytes(2048)).toBe('2 KB');
    expect(fmtBytes(5 * 1_048_576)).toBe('5.0 MB');
    expect(fmtPrice(1500000)).toBe('1 500 000');
    expect(fmtPrice('990000.00')).toBe('990 000');
    expect(fmtPrice(null)).toBeNull();
    expect(fmtPrice('free')).toBe('free');
    expect(hostFromUrl('https://cc.example.uz/api/v1')).toBe('cc.example.uz');
    expect(hostFromUrl('')).toBe('');
    expect(fmtDate('2026-12-31T10:00:00Z')).toBe('2026-12-31');
    expect(fmtDate(null)).toBe('—');
    expect(fmtClock(null)).toBe('—');
  });

  it('relative time buckets', () => {
    const now = Date.parse('2026-09-16T12:00:00Z');
    expect(relativeParts('2026-09-16T11:59:30Z', now)).toEqual({ unit: 'now', n: 0 });
    expect(relativeParts('2026-09-16T11:55:00Z', now)).toEqual({ unit: 'min', n: 5 });
    expect(relativeParts('2026-09-16T09:00:00Z', now)).toEqual({ unit: 'hour', n: 3 });
    expect(relativeParts('2026-09-14T12:00:00Z', now)).toEqual({ unit: 'day', n: 2 });
    expect(relativeParts(undefined, now)).toBeNull();
  });

  it('log helpers', () => {
    expect(logLevelClass('CRITICAL')).toBe('error');
    expect(logLevelClass('warning')).toBe('warning');
    expect(logLevelClass('DEBUG')).toBe('debug');
    expect(logLevelClass('INFO')).toBe('info');
    expect(logTs('2026-06-12 14:32:01,123')).toBe('2026-06-12 14:32:01');
  });
});

describe('sync state rules', () => {
  it('priority: busy > close conflict > close pending > replay > off > live > down', () => {
    const conflict = { enabled: true, is_online: true, shift_close: { state: 'CONFLICT', message: 'mismatch' } };
    expect(deriveSyncPill(conflict, true).label).toBe('sync.busy');
    expect(deriveSyncPill(conflict)).toMatchObject({ label: 'sync.closeConflict', tone: 'danger', details: ['mismatch'] });
    expect(deriveSyncPill({ enabled: true, is_online: true, shift_close: { pending_count: 2 } })).toMatchObject({ label: 'sync.closePending', tone: 'warn' });
    expect(deriveSyncPill({ enabled: true, is_online: true, full_pull_pending: true })).toMatchObject({ label: 'sync.replayPending', tone: 'warn' });
    expect(deriveSyncPill({ enabled: true, full_pull_state: 'PENDING' }).label).toBe('sync.replayPending');
    expect(deriveSyncPill({ enabled: false })).toMatchObject({ label: 'sync.off', tone: 'muted' });
    expect(deriveSyncPill({ enabled: true, is_online: true, pending_count: 4 })).toMatchObject({ label: 'sync.live', tone: 'ok', pending: 4 });
    expect(deriveSyncPill({ enabled: true, is_online: false })).toMatchObject({ label: 'sync.down', tone: 'danger' });
    expect(deriveSyncPill(undefined).label).toBe('sync.off');
  });

  it('surfaces distinct pull and push errors', () => {
    const pill = deriveSyncPill({ enabled: true, last_pull_error: 'feed 500', last_error: 'feed 500' });
    expect(pill.details).toEqual(['feed 500']);
    expect(deriveSyncPill({ enabled: true, last_pull_error: 'a', last_error: 'b' }).details).toEqual(['a', 'b']);
  });

  it('shift close + replay flags', () => {
    expect(shiftCloseState({ conflict_count: 1, pending_count: 3 })).toEqual({ conflict: true, pending: false });
    expect(shiftCloseState({ state: 'pending' })).toEqual({ conflict: false, pending: true });
    expect(shiftCloseState(undefined)).toEqual({ conflict: false, pending: false });
    expect(isReplayPending({ full_pull_state: 'not_requested' })).toBe(false);
  });
});

describe('config import parser (ESM)', () => {
  it('accepts wrapped JSON and filters unknown keys', () => {
    expect(parseConfigImport('{"config":{"PORT":"8000","X":"y"}}', ['PORT'])).toEqual({ ok: true, data: { PORT: '8000' } });
  });
  it('keeps KEY=VALUE compatibility', () => {
    expect(parseConfigImport('# c\r\nPORT=8123\nNOPE\n', ['PORT'])).toEqual({ ok: true, data: { PORT: '8123' } });
  });
  it('rejects empty, invalid and unrecognised files', () => {
    expect(parseConfigImport('', [])).toEqual({ ok: false, error: 'The configuration file is empty.' });
    expect(parseConfigImport('{"config": ', ['PORT'])).toEqual({ ok: false, error: 'The configuration JSON is invalid.' });
    expect(parseConfigImport('[1]', ['PORT'])).toEqual({ ok: false, error: 'Expected a JSON configuration object.' });
    expect(parseConfigImport('{"config": []}', ['PORT'])).toEqual({ ok: false, error: 'The JSON config field must be an object.' });
    expect(parseConfigImport('{"A":1}', ['PORT'])).toEqual({ ok: false, error: 'The file contains no recognized Alpha POS settings.' });
    expect(parseConfigImport('# only comments', [])).toEqual({ ok: false, error: 'The file contains no configuration settings.' });
  });
});

describe('plans, prefs, page helpers', () => {
  it('normalizes plan catalogues and matches the full current name', () => {
    const plans = normalizePlans({ plans: [{ id: 7, name: 'Standard Plan', price_uzs: 250000, features: ['a', 'b'] }, { code: 'pro', title: 'Pro' }] });
    expect(plans[0]).toMatchObject({ id: '7', name: 'Standard Plan', price: 250000, desc: 'a · b', currency: 'UZS', period: 'mo' });
    expect(plans[1]).toMatchObject({ id: 'pro', name: 'Pro' });
    expect(normalizePlans([{ plan_id: 'x' }])[0].id).toBe('x');
    expect(normalizePlans(null)).toEqual([]);
    expect(findCurrentPlan(plans, true, 'standard plan')?.id).toBe('7');
    expect(findCurrentPlan(plans, false, 'Standard Plan')).toBeUndefined();
    expect(findCurrentPlan(FALLBACK_PLANS, true, 'pro')?.name).toBe('Pro');
  });

  it('migrates legacy theme directions and validates language', () => {
    expect(migratePrefs({ dir: 'noir', lang: 'RU' })).toEqual({ theme: 'dark', lang: 'ru' });
    expect(migratePrefs({ dir: 'porcelain' })).toEqual({ theme: 'light' });
    expect(migratePrefs({ dir: 'atelier', theme: 'system' })).toEqual({ theme: 'system' });
    expect(migratePrefs({ lang: 'de' })).toEqual({});
    expect(readCachedPrefs({ getItem: () => '{broken' })).toEqual(DEFAULT_PREFS);
    expect(readCachedPrefs({ getItem: () => '{"theme":"dark","lang":"uz"}' })).toEqual({ theme: 'dark', lang: 'uz' });
  });

  it('counts changed config keys treating missing as empty', () => {
    expect(changedKeys({ A: '1', B: '' }, { A: '1', B: '' })).toEqual([]);
    expect(changedKeys({ A: '1' }, { A: '2', C: '' })).toEqual(['A']);
    expect(changedKeys({ A: '1' }, { A: '1', C: 'x' })).toEqual(['C']);
  });

  it('filters logs newest-first by level and query', () => {
    const entries = [
      { ts: '1', level: 'INFO', logger: 'a', message: 'boot' },
      { ts: '2', level: 'ERROR', logger: 'sync', message: 'Push failed' },
      { ts: '3', level: 'WARNING', logger: 'b', message: 'slow' },
    ];
    expect(filterLogs(entries, 'all', '').map((r) => r.entry.ts)).toEqual(['3', '2', '1']);
    expect(filterLogs(entries, 'error', '').map((r) => r.entry.ts)).toEqual(['2']);
    expect(filterLogs(entries, 'info', '').map((r) => r.entry.ts)).toEqual(['1']);
    expect(filterLogs(entries, 'all', 'SYNC').map((r) => r.entry.ts)).toEqual(['2']);
  });
});
