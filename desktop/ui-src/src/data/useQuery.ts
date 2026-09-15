import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { api, type ApiOptions, type MethodName, type ResultOf } from '../bridge/methods';
import type { BackendResult } from '../bridge/transport';
import { store, type QueryState, type Subscriber } from './store';

export const SERVER_KEY = 'server_status';
export const DJANGO_GATE_TIMEOUT = 180_000;

export interface QueryOptions {
  interval?: number | null;
  enabled?: boolean;
  refetchOnMount?: 'always' | 'ifMissing' | 'never';
  timeoutMs?: number;
  /** Queries that call ensure_django(): run once with a long timeout until Django is ready. */
  gate?: 'django';
}

export interface QueryResult<T extends BackendResult> extends Omit<QueryState, 'data'> {
  data: T | undefined;
  /** Gated query waiting for the backend to finish preparing the database. */
  preparing: boolean;
  refetch: () => Promise<BackendResult>;
}

function useStoreValue<T>(key: string, select: (state: QueryState) => T): T {
  const [value, setValue] = useState(() => select(store.getState(key)));
  const selectRef = useRef(select);
  selectRef.current = select;
  useEffect(() => {
    const sync = () => setValue(() => selectRef.current(store.getState(key)));
    sync();
    return store.listen(key, sync);
  }, [key]);
  return value;
}

/** True once server_status reports django_ready. Re-renders only on change. */
export function useDjangoReady(active = true): boolean {
  return useStoreValue(SERVER_KEY, (s) => !active || (s.data as { django_ready?: boolean } | undefined)?.django_ready === true);
}

export function useQuery<T extends BackendResult>(
  key: string,
  fetcher: (options: ApiOptions) => Promise<T>,
  options: QueryOptions = {},
): QueryResult<T> {
  const { interval = null, enabled = true, refetchOnMount = 'always', timeoutMs, gate } = options;
  const djangoReady = useDjangoReady(gate === 'django');
  const gated = gate === 'django' && !djangoReady;
  const effectiveInterval = gated ? null : interval;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const timeoutRef = useRef<number | undefined>(timeoutMs);
  timeoutRef.current = gated ? DJANGO_GATE_TIMEOUT : timeoutMs;

  const [, setTick] = useState(0);
  const subRef = useRef<Subscriber | null>(null);
  const state = store.getState(key);
  const renderedRef = useRef(state);
  renderedRef.current = state;

  useEffect(() => {
    if (!enabled) return undefined;
    store.setFetcher(key, (signal) => fetcherRef.current({ timeoutMs: timeoutRef.current, signal }));
    const sub: Subscriber = { interval: effectiveInterval, listener: () => setTick((n) => n + 1) };
    subRef.current = sub;
    const unsubscribe = store.subscribe(key, sub, refetchOnMount);
    // Data may have landed between render and this effect (e.g. fetched by
    // another subscriber); the store does not re-notify identical payloads.
    if (store.getState(key) !== renderedRef.current) setTick((n) => n + 1);
    return () => {
      unsubscribe();
      subRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  useEffect(() => {
    if (subRef.current) store.updateSubscriber(key, subRef.current, effectiveInterval);
  }, [key, effectiveInterval]);

  // Django just became ready: refresh gated data that may have timed out or be partial.
  const wasGated = useRef(gated);
  useEffect(() => {
    if (wasGated.current && !gated && enabled && !store.isInflight(key)) void store.fetch(key, false);
    wasGated.current = gated;
  }, [gated, enabled, key]);

  const refetch = useMemo(() => () => store.fetch(key, true), [key]);
  return {
    ...state,
    data: state.data as T | undefined,
    preparing: gated && (state.data === undefined || state.status === 'error'),
    refetch,
  };
}

/** Convenience: a query whose key is the bridge method name. */
export function useMethodQuery<M extends MethodName>(
  method: M,
  options: QueryOptions & { args?: unknown[]; key?: string } = {},
): QueryResult<ResultOf<M>> {
  const { args, key, ...rest } = options;
  const argsRef = useRef(args);
  argsRef.current = args;
  return useQuery<ResultOf<M>>(
    key ?? method,
    (o) => api(method, argsRef.current ?? [], o),
    rest,
  );
}
