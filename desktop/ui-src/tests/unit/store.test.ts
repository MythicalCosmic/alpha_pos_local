import { afterEach, describe, expect, it, vi } from 'vitest';
import type { BackendResult } from '../../src/bridge/transport';
import { backoffDelay, createStore, MAX_BACKOFF_MS } from '../../src/data/store';

function setup() {
  vi.useFakeTimers();
  let hidden = false;
  let onVisibility: (() => void) | null = null;
  const store = createStore({
    now: () => Date.now(),
    setTimeout: (fn, ms) => setTimeout(fn, ms),
    clearTimeout: (id) => clearTimeout(id),
    isHidden: () => hidden,
    onVisibilityChange: (fn) => {
      onVisibility = fn;
      return () => { onVisibility = null; };
    },
  });
  return {
    store,
    setHidden(value: boolean) {
      hidden = value;
      onVisibility?.();
    },
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => { resolve = r; });
  return { promise, resolve };
}

const ok = (extra: Record<string, unknown> = {}): BackendResult => ({ ok: true, ...extra });
const noop = () => {};

afterEach(() => {
  vi.useRealTimers();
});

describe('query store', () => {
  it('dedupes concurrent fetches of the same key', async () => {
    const { store } = setup();
    const d = deferred<BackendResult>();
    const fetcher = vi.fn(() => d.promise);
    store.setFetcher('a', fetcher);
    store.subscribe('a', { interval: null, listener: noop });
    store.subscribe('a', { interval: null, listener: noop });
    void store.fetch('a');
    void store.fetch('a');
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(store.isInflight('a')).toBe(true);
    d.resolve(ok({ v: 1 }));
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState('a').data).toEqual({ ok: true, v: 1 });
    expect(store.isInflight('a')).toBe(false);
  });

  it('polls only while subscribed', async () => {
    const { store } = setup();
    const fetcher = vi.fn(async () => ok());
    store.setFetcher('p', fetcher);
    const unsubscribe = store.subscribe('p', { interval: 1000, listener: noop });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(fetcher).toHaveBeenCalledTimes(2);
    unsubscribe();
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('uses the fastest interval among subscribers and never polls without one', async () => {
    const { store } = setup();
    const fetcher = vi.fn(async () => ok());
    store.setFetcher('m', fetcher);
    store.subscribe('m', { interval: null, listener: noop });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    const fast = { interval: 5000, listener: noop };
    const unsub = store.subscribe('m', fast, 'never');
    // Data is already older than the new interval: refresh right away.
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetcher).toHaveBeenCalledTimes(3);
    store.updateSubscriber('m', fast, 60_000);
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetcher).toHaveBeenCalledTimes(3);
    unsub();
  });

  it('restarts the timer from the response time, not the request time', async () => {
    const { store } = setup();
    const fetcher = vi.fn(() => new Promise<BackendResult>((resolve) => setTimeout(() => resolve(ok()), 500)));
    store.setFetcher('slow', fetcher);
    store.subscribe('slow', { interval: 1000, listener: noop });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1400);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('pauses while hidden and refetches on resume when stale', async () => {
    const { store, setHidden } = setup();
    const fetcher = vi.fn(async () => ok());
    store.setFetcher('v', fetcher);
    store.subscribe('v', { interval: 1000, listener: noop });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    setHidden(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetcher).toHaveBeenCalledTimes(1);
    setHidden(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('does not refetch on resume when data is still fresh', async () => {
    const { store, setHidden } = setup();
    const fetcher = vi.fn(async () => ok());
    store.setFetcher('f', fetcher);
    store.subscribe('f', { interval: 10_000, listener: noop });
    await vi.advanceTimersByTimeAsync(1000);
    setHidden(true);
    await vi.advanceTimersByTimeAsync(1000);
    setHidden(false);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(8000);
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('backs off exponentially on errors up to 60 s', async () => {
    expect(backoffDelay(1000, 0)).toBe(1000);
    expect(backoffDelay(1000, 1)).toBe(2000);
    expect(backoffDelay(1000, 3)).toBe(8000);
    expect(backoffDelay(5000, 10)).toBe(MAX_BACKOFF_MS);
    expect(backoffDelay(90_000, 2)).toBe(90_000);

    const { store } = setup();
    const fetcher = vi.fn(async (): Promise<BackendResult> => ({ ok: false, error: 'down', kind: 'timeout' }));
    store.setFetcher('e', fetcher);
    store.subscribe('e', { interval: 1000, listener: noop });
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState('e').failures).toBe(1);
    expect(store.getState('e').transportFailures).toBe(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetcher).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(4000);
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it('keeps data and marks it stale when a refresh fails', async () => {
    const { store } = setup();
    const results: BackendResult[] = [ok({ n: 1 }), { ok: false, error: 'boom' }, ok({ n: 2 })];
    store.setFetcher('s', async () => results.shift()!);
    store.subscribe('s', { interval: null, listener: noop });
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState('s')).toMatchObject({ stale: false, status: 'success' });
    await store.fetch('s');
    expect(store.getState('s')).toMatchObject({ stale: true, status: 'error', data: { n: 1 }, transportFailures: 0 });
    await store.fetch('s');
    expect(store.getState('s')).toMatchObject({ stale: false, status: 'success', data: { n: 2 }, failures: 0 });
  });

  it('does not notify subscribers when a poll returns identical data', async () => {
    const { store } = setup();
    const listener = vi.fn();
    store.setFetcher('same', async () => ok({ x: [1, 2] }));
    store.subscribe('same', { interval: 1000, listener });
    await vi.advanceTimersByTimeAsync(0);
    const first = store.getState('same').data;
    const calls = listener.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000);
    expect(store.getState('same').data).toBe(first);
    expect(listener.mock.calls.length).toBe(calls);
  });

  it('invalidation refetches subscribed keys only', async () => {
    const { store } = setup();
    const a = vi.fn(async () => ok());
    const b = vi.fn(async () => ok());
    store.setFetcher('inv', a);
    store.setFetcher('other', b);
    store.subscribe('inv', { interval: null, listener: noop });
    await vi.advanceTimersByTimeAsync(0);
    store.invalidate(['inv', 'other']);
    await vi.advanceTimersByTimeAsync(0);
    expect(a).toHaveBeenCalledTimes(2);
    expect(b).toHaveBeenCalledTimes(0);
  });

  it('invalidation matches key prefixes and supersedes in-flight responses', async () => {
    const { store } = setup();
    const first = deferred<BackendResult>();
    const replies = [first.promise, Promise.resolve(ok({ fresh: true }))];
    const fetcher = vi.fn(() => replies.shift()!);
    store.setFetcher('logs:app', fetcher);
    store.subscribe('logs:app', { interval: null, listener: noop });
    store.invalidate('logs');
    first.resolve(ok({ fresh: false }));
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(0);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(store.getState('logs:app').data).toMatchObject({ fresh: true });
  });

  it('setData applies optimistic values and ignores a response already on the wire', async () => {
    const { store } = setup();
    const d = deferred<BackendResult>();
    store.setFetcher('opt', () => d.promise);
    store.subscribe('opt', { interval: null, listener: noop });
    store.setData('opt', () => ok({ mode: 'live' }));
    d.resolve(ok({ mode: 'off' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(store.getState('opt').data).toMatchObject({ mode: 'live' });
  });
});
