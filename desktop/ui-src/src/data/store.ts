// Tiny query cache: one entry per key, in-flight dedupe, polling only while
// someone is subscribed, timers restarted from the response time, exponential
// error backoff, and a full pause while the window is hidden.
import type { BackendResult, BridgeErrorKind } from '../bridge/transport';

export type Fetcher = (signal: AbortSignal) => Promise<BackendResult>;

export interface QueryState {
  data: BackendResult | undefined;
  error: BackendResult | undefined;
  /** idle: never fetched; loading: first fetch pending; success/error: last outcome. */
  status: 'idle' | 'loading' | 'success' | 'error';
  fetching: boolean;
  /** Data exists but the most recent refresh failed. */
  stale: boolean;
  updatedAt: number;
  failures: number;
  transportFailures: number;
}

export interface Subscriber {
  interval: number | null;
  listener: () => void;
}

interface Entry {
  key: string;
  state: QueryState;
  fetcher: Fetcher | undefined;
  subs: Set<Subscriber>;
  passive: Set<() => void>;
  inflight: Promise<BackendResult> | null;
  timer: ReturnType<typeof setTimeout> | null;
  finishedAt: number;
  raw: string | undefined;
  generation: number;
}

export interface StoreDeps {
  now: () => number;
  setTimeout: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  clearTimeout: (id: ReturnType<typeof setTimeout>) => void;
  isHidden: () => boolean;
  onVisibilityChange: (fn: () => void) => () => void;
}

export const MAX_BACKOFF_MS = 60_000;
const TRANSPORT_KINDS: ReadonlySet<BridgeErrorKind | undefined> = new Set(['transport', 'timeout']);

const INITIAL: QueryState = {
  data: undefined, error: undefined, status: 'idle', fetching: false,
  stale: false, updatedAt: 0, failures: 0, transportFailures: 0,
};

function browserDeps(): StoreDeps {
  const hasDoc = typeof document !== 'undefined';
  return {
    now: () => Date.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    isHidden: () => hasDoc && document.visibilityState === 'hidden',
    onVisibilityChange: (fn) => {
      if (!hasDoc) return () => {};
      document.addEventListener('visibilitychange', fn);
      return () => document.removeEventListener('visibilitychange', fn);
    },
  };
}

export function backoffDelay(interval: number, failures: number): number {
  if (failures <= 0) return interval;
  const cap = Math.max(MAX_BACKOFF_MS, interval);
  return Math.min(interval * 2 ** failures, cap);
}

export type QueryStore = ReturnType<typeof createStore>;

export function createStore(overrides: Partial<StoreDeps> = {}) {
  const deps: StoreDeps = { ...browserDeps(), ...overrides };
  const entries = new Map<string, Entry>();

  function entry(key: string): Entry {
    let e = entries.get(key);
    if (!e) {
      e = {
        key, state: INITIAL, fetcher: undefined, subs: new Set(), passive: new Set(),
        inflight: null, timer: null, finishedAt: 0, raw: undefined, generation: 0,
      };
      entries.set(key, e);
    }
    return e;
  }

  function emit(e: Entry) {
    e.subs.forEach((s) => s.listener());
    e.passive.forEach((fn) => fn());
  }

  function commit(e: Entry, next: QueryState, notify = true) {
    const prev = e.state;
    e.state = next;
    if (!notify) return;
    if (
      prev.data !== next.data || prev.error !== next.error || prev.status !== next.status
      || prev.stale !== next.stale || prev.fetching !== next.fetching
    ) emit(e);
  }

  function effectiveInterval(e: Entry): number | null {
    let min: number | null = null;
    e.subs.forEach((s) => {
      if (s.interval != null && s.interval > 0 && (min === null || s.interval < min)) min = s.interval;
    });
    return min;
  }

  function clearTimer(e: Entry) {
    if (e.timer !== null) {
      deps.clearTimeout(e.timer);
      e.timer = null;
    }
  }

  function schedule(e: Entry) {
    clearTimer(e);
    const interval = effectiveInterval(e);
    if (interval === null || e.inflight || deps.isHidden() || !e.fetcher) return;
    const delay = backoffDelay(interval, e.state.failures);
    const due = e.finishedAt ? e.finishedAt + delay : deps.now();
    const wait = Math.max(0, due - deps.now());
    e.timer = deps.setTimeout(() => {
      e.timer = null;
      void fetchEntry(e, false);
    }, wait);
  }

  function fetchEntry(e: Entry, manual: boolean): Promise<BackendResult> {
    if (e.inflight) return e.inflight;
    const fetcher = e.fetcher;
    if (!fetcher) return Promise.resolve({ ok: false, error: 'No fetcher registered' });
    clearTimer(e);
    const generation = e.generation;
    const controller = new AbortController();
    const firstLoad = e.state.data === undefined;
    commit(
      e,
      { ...e.state, fetching: true, status: firstLoad ? 'loading' : e.state.status },
      firstLoad || manual,
    );
    const run = (async () => {
      let result: BackendResult;
      try {
        result = await fetcher(controller.signal);
      } catch (error) {
        result = { ok: false, error: error instanceof Error ? error.message : String(error), kind: 'transport' };
      }
      e.inflight = null;
      e.finishedAt = deps.now();
      if (generation !== e.generation) {
        schedule(e);
        return result;
      }
      const s = e.state;
      if (result && result.ok !== false) {
        const raw = safeStringify(result);
        const same = raw !== undefined && raw === e.raw;
        e.raw = raw;
        commit(e, {
          data: same ? s.data : result, error: undefined, status: 'success', fetching: false,
          stale: false, updatedAt: e.finishedAt, failures: 0, transportFailures: 0,
        }, s.data === undefined || !same || s.status !== 'success' || s.stale || manual || s.fetching !== false && manual);
      } else {
        const transport = TRANSPORT_KINDS.has(result?.kind);
        commit(e, {
          data: s.data, error: result, status: 'error', fetching: false,
          stale: s.data !== undefined, updatedAt: s.updatedAt,
          failures: s.failures + 1,
          transportFailures: transport ? s.transportFailures + 1 : 0,
        });
      }
      schedule(e);
      return result;
    })();
    e.inflight = run;
    return run;
  }

  const stopVisibility = deps.onVisibilityChange(() => {
    if (deps.isHidden()) {
      entries.forEach(clearTimer);
      return;
    }
    entries.forEach((e) => {
      const interval = effectiveInterval(e);
      if (interval === null || e.inflight || !e.fetcher) return;
      if (deps.now() - e.finishedAt >= backoffDelay(interval, e.state.failures)) void fetchEntry(e, false);
      else schedule(e);
    });
  });

  return {
    getState(key: string): QueryState {
      return entries.get(key)?.state ?? INITIAL;
    },
    setFetcher(key: string, fetcher: Fetcher) {
      entry(key).fetcher = fetcher;
    },
    /** Register an active subscriber. `refetch` 'always' fetches on mount, 'ifMissing' only without data. */
    subscribe(key: string, sub: Subscriber, refetch: 'always' | 'ifMissing' | 'never' = 'always'): () => void {
      const e = entry(key);
      e.subs.add(sub);
      const wantFetch = refetch === 'always' || (refetch === 'ifMissing' && e.state.data === undefined);
      if (wantFetch && !deps.isHidden()) void fetchEntry(e, false);
      else schedule(e);
      return () => {
        e.subs.delete(sub);
        if (effectiveInterval(e) === null) clearTimer(e);
        else schedule(e);
      };
    },
    /** Passive listener: observes state without driving fetches or polling. */
    listen(key: string, fn: () => void): () => void {
      const e = entry(key);
      e.passive.add(fn);
      return () => e.passive.delete(fn);
    },
    updateSubscriber(key: string, sub: Subscriber, interval: number | null) {
      const e = entry(key);
      if (sub.interval === interval) return;
      sub.interval = interval;
      if (e.subs.has(sub)) schedule(e);
    },
    fetch(key: string, manual = true): Promise<BackendResult> {
      return fetchEntry(entry(key), manual);
    },
    setData(key: string, update: (data: BackendResult | undefined) => BackendResult | undefined) {
      const e = entry(key);
      const data = update(e.state.data);
      e.raw = data === undefined ? undefined : safeStringify(data);
      // A local write supersedes any response already on the wire.
      if (e.inflight) e.generation += 1;
      commit(e, { ...e.state, data, stale: false, status: data === undefined ? e.state.status : 'success' });
    },
    /** Refetch subscribed keys now; unsubscribed keys refetch on next mount. */
    invalidate(keys: string | string[] | ((key: string) => boolean)) {
      const match = typeof keys === 'function'
        ? keys
        : ((list: string[]) => (key: string) => list.some((k) => key === k || key.startsWith(k + ':')))(Array.isArray(keys) ? keys : [keys]);
      entries.forEach((e) => {
        if (!match(e.key)) return;
        e.finishedAt = 0;
        if (e.subs.size && e.fetcher) {
          if (e.inflight) {
            e.generation += 1;
            const again = e.inflight.then(() => fetchEntry(e, true));
            void again;
          } else void fetchEntry(e, true);
        }
      });
    },
    isInflight(key: string): boolean {
      return !!entries.get(key)?.inflight;
    },
    destroy() {
      stopVisibility();
      entries.forEach(clearTimer);
      entries.clear();
    },
  };
}

function safeStringify(value: unknown): string | undefined {
  try {
    return JSON.stringify(value);
  } catch {
    return undefined;
  }
}

export const store = createStore();
