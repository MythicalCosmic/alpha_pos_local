import { expect, type Page } from '@playwright/test';
import { FIXTURES, initialState, type FixtureContext, type MockState, type Scenario } from './fixtures/bridge-fixtures';

export interface CallRecord {
  method: string;
  args: unknown[];
  at: number;
}

export interface MockOptions {
  scenario?: Scenario;
  /** Response delay in ms per method. */
  delays?: Record<string, number>;
  /** Methods whose requests never get a response. */
  hang?: string[];
  /** true → every call is 403; array → only those methods. */
  forbidden?: boolean | string[];
  overrides?: Record<string, (ctx: FixtureContext) => Record<string, unknown>>;
  prefs?: { theme?: string; lang?: string };
}

export interface MockBridge {
  state: MockState;
  calls: CallRecord[];
  count(method: string): number;
  clear(): void;
  waitForCall(method: string, atLeast?: number, timeout?: number): Promise<void>;
}

export async function installMockBridge(page: Page, options: MockOptions = {}): Promise<MockBridge> {
  const state = initialState(options.scenario ?? 'healthy');
  if (options.prefs) state.prefs = { ...options.prefs };
  const calls: CallRecord[] = [];
  const perMethod = new Map<string, number>();

  if (options.prefs) {
    await page.addInitScript((prefs) => {
      try {
        localStorage.setItem('alphapos.panel.prefs', JSON.stringify({ theme: 'system', lang: 'en', ...prefs }));
      } catch {
        /* ignore */
      }
    }, options.prefs);
  }

  await page.route('**/api/*', async (route) => {
    const request = route.request();
    const method = new URL(request.url()).pathname.split('/').pop() || '';
    let args: unknown[] = [];
    try {
      args = JSON.parse(request.postData() || '[]');
    } catch {
      args = [];
    }
    calls.push({ method, args, at: Date.now() });
    const call = perMethod.get(method) ?? 0;
    perMethod.set(method, call + 1);

    const forbidden = options.forbidden === true || (Array.isArray(options.forbidden) && options.forbidden.includes(method));
    if (forbidden) {
      await route.fulfill({ status: 403, contentType: 'application/json', body: '{"ok":false,"error":"forbidden"}' });
      return;
    }
    if (options.hang?.includes(method)) return; // never answered
    const delay = options.delays?.[method];
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    const fixture = options.overrides?.[method] ?? FIXTURES[method];
    if (!fixture) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: `no method ${method}` }) });
      return;
    }
    try {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(fixture({ args, state, call })) });
    } catch {
      /* page closed while delayed */
    }
  });

  return {
    state,
    calls,
    count: (method) => calls.filter((c) => c.method === method).length,
    clear: () => { calls.length = 0; },
    async waitForCall(method, atLeast = 1, timeout = 10_000) {
      await expect.poll(() => calls.filter((c) => c.method === method).length, { timeout }).toBeGreaterThanOrEqual(atLeast);
    },
  };
}
