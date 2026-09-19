import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHttpTransport } from '../../src/bridge/http';
import { selectBridge } from '../../src/bridge/index';
import { METHODS } from '../../src/bridge/methods';

afterEach(() => {
  vi.useRealTimers();
});

const response = (status: number, body: unknown) => new Response(typeof body === 'string' ? body : JSON.stringify(body), { status });

describe('http transport', () => {
  it('posts args with the token and returns the JSON result', async () => {
    const fetchImpl = vi.fn(async (_url: string, _init: RequestInit) => response(200, { ok: true, running: false }));
    const transport = createHttpTransport(() => 'tok', fetchImpl);
    const result = await transport.call('app_logs', ['app', 2000], { timeoutMs: 1000 });
    expect(result).toEqual({ ok: true, running: false });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('/api/app_logs');
    expect(init.method).toBe('POST');
    expect((init.headers as Record<string, string>)['X-Control-Token']).toBe('tok');
    expect(init.body).toBe('["app",2000]');
  });

  it('normalizes 403, HTTP errors, bad JSON and network faults', async () => {
    const cases: Array<[() => Promise<Response>, string]> = [
      [async () => response(403, { ok: false, error: 'forbidden' }), 'auth'],
      [async () => response(500, 'oops'), 'http'],
      [async () => response(200, 'not json'), 'http'],
      [async () => response(200, '[1,2]'), 'http'],
      [async () => { throw new TypeError('Failed to fetch'); }, 'transport'],
    ];
    for (const [impl, kind] of cases) {
      const result = await createHttpTransport(() => '', impl).call('x', [], { timeoutMs: 1000 });
      expect(result).toMatchObject({ ok: false, kind });
    }
  });

  it('aborts and reports a timeout', async () => {
    vi.useFakeTimers();
    const fetchImpl = (_url: string, init: RequestInit) => new Promise<Response>((_, reject) => {
      init.signal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
    });
    const pending = createHttpTransport(() => '', fetchImpl).call('slow', [], { timeoutMs: 15_000 });
    await vi.advanceTimersByTimeAsync(15_000);
    await expect(pending).resolves.toMatchObject({ ok: false, kind: 'timeout' });
  });
});

describe('bridge selection', () => {
  const pageWithToken = (content: string) => ({
    querySelector: () => ({ getAttribute: () => content }),
  }) as unknown as Document;

  it('prefers the __ALPHA_BRIDGE__ override, then same-origin HTTP', () => {
    const call = vi.fn();
    expect(selectBridge({ __ALPHA_BRIDGE__: { call } } as unknown as Window).transport.name).toBe('custom');
    expect(selectBridge({ document: pageWithToken('a'.repeat(64)) } as unknown as Window).transport.name).toBe('http');
    expect(selectBridge({} as Window).transport.name).toBe('http');
  });

  it('declares long timeouts for destructive and cloud operations', () => {
    expect(METHODS.server_status).toBe(15_000);
    expect(METHODS.run_setup).toBe(600_000);
    expect(METHODS.flush_database).toBe(600_000);
    expect(METHODS.factory_reset).toBe(600_000);
    for (const [name, ms] of Object.entries(METHODS)) {
      if (name.startsWith('cloud_') || name.startsWith('check_updates_')) expect(ms, name).toBe(120_000);
    }
  });
});
