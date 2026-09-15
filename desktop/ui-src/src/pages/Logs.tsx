import { useEffect, useMemo, useState } from 'preact/hooks';
import { api } from '../bridge/methods';
import type { LogEntry, LogsResult } from '../bridge/types';
import type { BackendResult } from '../bridge/transport';
import { IconRefresh } from '../components/icons';
import { QueryBoundary } from '../components/QueryBoundary';
import { VirtualList } from '../components/VirtualList';
import { Button, Card, CopyButton, EmptyState, KeyValue, KV, Segmented, Switch } from '../components/ui';
import { POLL } from '../data/queries';
import { useQuery } from '../data/useQuery';
import { useT, type I18nKey } from '../i18n';
import { logLevelClass, logTs, type LogLevelClass } from '../lib/format';

type Source = 'app' | 'error';
type Level = 'all' | 'error' | 'warning' | 'info';

export const ROW_HEIGHT = 28;
const LOG_LIMIT = 2000;
const EMPTY: LogEntry[] = [];

interface Row {
  entry: LogEntry;
  cls: LogLevelClass;
}

export function filterLogs(entries: readonly LogEntry[], level: Level, query: string): Row[] {
  const q = query.trim().toLowerCase();
  const out: Row[] = [];
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    const cls = logLevelClass(entry.level);
    if (level === 'error' && cls !== 'error') continue;
    if (level === 'warning' && cls !== 'warning') continue;
    if (level === 'info' && (cls === 'error' || cls === 'warning')) continue;
    if (q && !(
      (entry.message || '').toLowerCase().includes(q)
      || (entry.logger || '').toLowerCase().includes(q)
      || (entry.level || '').toLowerCase().includes(q)
    )) continue;
    out.push({ entry, cls });
  }
  return out;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

const LEVELS: ReadonlyArray<{ id: Level; key: I18nKey; count: 'total' | 'error' | 'warning' | 'info' }> = [
  { id: 'all', key: 'log.all', count: 'total' },
  { id: 'error', key: 'log.errors', count: 'error' },
  { id: 'warning', key: 'log.warnings', count: 'warning' },
  { id: 'info', key: 'log.info', count: 'info' },
];

export default function Logs() {
  const t = useT();
  const [source, setSource] = useState<Source>('app');
  const [level, setLevel] = useState<Level>('all');
  const [query, setQuery] = useState('');
  const [live, setLive] = useState(false);
  const [selected, setSelected] = useState<LogEntry | null>(null);
  const search = useDebounced(query, 150);

  const q = useQuery<BackendResult & LogsResult>(
    `app_logs:${source}`,
    (o) => api('app_logs', [source, LOG_LIMIT], o),
    { interval: live ? POLL.logsLive : null },
  );
  const entries = q.data?.entries ?? EMPTY;
  const rows = useMemo(() => filterLogs(entries, level, search), [entries, level, search]);
  const counts = q.data?.counts;

  return (
    <div class="page">
      <p class="page-sub">{t('log.sub')}</p>
      <div class="toolbar">
        <Segmented
          options={[{ value: 'app' as Source, label: t('log.all') }, { value: 'error' as Source, label: t('log.srcError') }]}
          value={source} label={t('log.source')} onChange={(s) => { setSource(s); setSelected(null); }}
        />
        <div class="row" role="group" aria-label={t('log.levels')}>
          {LEVELS.map((l) => (
            <button key={l.id} type="button" class="chip level-chip" aria-pressed={level === l.id} onClick={() => setLevel(l.id)}>
              {t(l.key)} <span class="mono muted">{counts ? counts[l.count] : 0}</span>
            </button>
          ))}
        </div>
        <input
          class="input" type="search" placeholder={t('log.searchPh')} aria-label={t('log.searchPh')}
          value={query} onInput={(e) => setQuery(e.currentTarget.value)}
        />
        <label class="row small">
          <Switch checked={live} label={t('log.live')} onChange={setLive} />
          <span aria-hidden="true">{t('log.live')}</span>
        </label>
        <Button size="sm" icon={<IconRefresh size={14} />} loading={q.fetching && q.data !== undefined} onClick={() => void q.refetch()}>
          {t('log.refresh')}
        </Button>
      </div>

      <QueryBoundary q={q} skeleton={10}>
        {(d) => d.exists === false ? (
          <EmptyState>{t('log.noFile')}</EmptyState>
        ) : (
          <div class="logs-layout">
            <div>
              {rows.length === 0 ? (
                <EmptyState>{t(entries.length ? 'log.noMatch' : 'log.empty')}</EmptyState>
              ) : (
                <VirtualList
                  items={rows} rowHeight={ROW_HEIGHT} height="max(260px, calc(100vh - 300px))" label={t('nav.logs')}
                  renderRow={(row, i, style) => (
                    <button
                      key={i} type="button" role="option" class="log-row" style={style}
                      aria-selected={row.entry === selected} onClick={() => setSelected(row.entry)}
                    >
                      <span class="log-ts">{logTs(row.entry.ts)}</span>
                      <span class={`log-lvl ${row.cls}`}>{row.entry.level}</span>
                      <span class="log-msg"><span class="log-logger mono">{row.entry.logger}</span>{row.entry.message.split('\n', 1)[0]}</span>
                    </button>
                  )}
                />
              )}
              <div class="row-between small muted mt-2">
                <span>{t('log.showing')} {rows.length}{rows.length !== entries.length ? ` / ${entries.length}` : ''}</span>
                {d.path ? <span class="mono wrap" title={d.path}>{d.path}</span> : null}
              </div>
            </div>
            <Card class="log-detail" title={t('log.detail')} actions={selected ? <CopyButton text={`${selected.ts} ${selected.level} ${selected.logger} ${selected.message}`} label={t('log.detail')} /> : null}>
              {selected ? (
                <>
                  <KeyValue>
                    <KV label={t('log.time')} mono>{logTs(selected.ts)}</KV>
                    <KV label={t('log.level')}>{selected.level}</KV>
                    <KV label={t('log.logger')} mono>{selected.logger}</KV>
                  </KeyValue>
                  <pre class="mt-3">{selected.message}</pre>
                </>
              ) : <p class="small muted">{t('log.selectHint')}</p>}
            </Card>
          </div>
        )}
      </QueryBoundary>
    </div>
  );
}
