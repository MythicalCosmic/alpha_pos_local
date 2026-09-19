import { expect, test, type Page } from '@playwright/test';
import { FIXTURES, initialState, type FixtureContext } from './fixtures/bridge-fixtures';
import { installMockBridge } from './mock-bridge';
import { openRoute, ROUTES, sharedAssertions, trackErrors, waitReady, waitReadyWithClock, type Route } from './support';

async function setHidden(page: Page, hidden: boolean) {
  await page.evaluate((h) => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => (h ? 'hidden' : 'visible') });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);
}

async function clickNav(page: Page, route: Route) {
  await page.locator(`nav.nav a[href="#/${route}"]`).click();
  await expect(page).toHaveURL(new RegExp(`#/${route}$`));
}

test.describe('backend phase', () => {
  test('boot never shows "Server stopped" and the power button stays disabled until running', async ({ page }) => {
    await page.addInitScript(() => {
      const w = window as unknown as { __sawStopped: boolean };
      w.__sawStopped = false;
      new MutationObserver(() => {
        if (/Server stopped|\bStopped\b|Server off/.test(document.body?.innerText || '')) w.__sawStopped = true;
      }).observe(document, { subtree: true, childList: true, characterData: true });
    });
    let booted = false;
    const mock = await installMockBridge(page, {
      scenario: 'booting',
      overrides: {
        server_status: ({ state, call }) => {
          if (call >= 2 && !booted) {
            booted = true;
            state.running = true;
            state.djangoReady = true;
          }
          return {
            ok: true, running: state.running, phase: state.running ? 'running' : 'stopped', desired_running: true,
            django_ready: state.djangoReady, started_at: state.running ? state.startedAt : null, last_error: null,
            port: 8000, lan_ip: '192.168.1.20', workers: {}, environment: { loaded: true }, database: {},
          };
        },
      },
    });
    await page.goto('/#/dashboard');
    const main = page.locator('main');
    await expect(main.getByText('Preparing database…').first()).toBeVisible();
    await expect(main.getByRole('button', { name: 'Start server' })).toBeDisabled();
    await expect(main.getByRole('button', { name: 'Stop server' })).toBeEnabled({ timeout: 15_000 });
    await expect(main.getByText('Server running')).toBeVisible();
    expect(mock.count('server_status')).toBeGreaterThanOrEqual(3);
    expect(await page.evaluate(() => (window as unknown as { __sawStopped: boolean }).__sawStopped)).toBe(false);
  });

  test('connecting state before first status: no "stopped", power disabled', async ({ page }) => {
    await installMockBridge(page, { scenario: 'healthy', hang: ['server_status'] });
    await page.goto('/#/dashboard');
    const main = page.locator('main');
    await expect(main.getByText('Connecting to the control service…')).toBeVisible();
    await expect(main.getByRole('button', { name: 'Start server' })).toBeDisabled();
    await expect(page.getByText('Server stopped')).toHaveCount(0);
  });

  test('server start failure keeps the stopped state and shows the backend error', async ({ page }) => {
    await installMockBridge(page, {
      scenario: 'stopped',
      overrides: { start_server: () => ({ ok: false, error: 'Address already in use: 0.0.0.0:8000' }) },
    });
    await page.goto('/#/dashboard');
    const main = page.locator('main');
    await main.getByRole('button', { name: 'Start server' }).click();
    await expect(page.locator('.toast', { hasText: 'Address already in use' })).toBeVisible();
    await expect(main.getByRole('button', { name: 'Start server' })).toBeEnabled();
    await expect(main.getByText('Server stopped')).toBeVisible();
  });

  test('server stop failure keeps the running state and toasts', async ({ page }) => {
    const mock = await installMockBridge(page, {
      scenario: 'healthy',
      overrides: { stop_server: () => ({ ok: false, error: 'A background sync is still finishing.' }) },
    });
    await page.goto('/#/dashboard');
    const main = page.locator('main');
    await main.getByRole('button', { name: 'Stop server' }).click();
    await expect(page.locator('.toast', { hasText: 'background sync is still finishing' })).toBeVisible();
    await expect(main.getByText('Server running')).toBeVisible();
    await expect(main.getByRole('button', { name: 'Stop server' })).toBeEnabled();
    expect(mock.state.running).toBe(true);
  });

  test('unreachable after repeated transport failures', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'healthy' });
    await page.goto('/#/dashboard');
    await waitReady(page);
    await page.route('**/api/server_status', (route) => route.abort('connectionrefused'));
    await expect(page.locator('main').getByText('Control service unreachable')).toBeVisible({ timeout: 25_000 });
    expect(mock.count('server_status')).toBeGreaterThanOrEqual(1);
  });
});

test.describe('data freshness', () => {
  const ENTRY_METHOD: Record<Route, string> = {
    dashboard: 'admin_credentials',
    license: 'license_plans',
    'local-audit': 'local_telegram_audit_status',
    config: 'get_config',
    tests: 'cloud_dead_letters',
    fiscal: 'fiscal_status',
    logs: 'app_logs',
    updates: 'update_status',
  };

  test('every page refreshes its data when entered', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'healthy' });
    await page.goto('/#/dashboard');
    await waitReady(page);
    for (const route of ROUTES) {
      const other: Route = route === 'dashboard' ? 'fiscal' : 'dashboard';
      await clickNav(page, other);
      await waitReady(page);
      const method = ENTRY_METHOD[route];
      const before = mock.count(method);
      await clickNav(page, route);
      await waitReady(page);
      await mock.waitForCall(method, before + 1);
    }
  });

  test('polling pauses while hidden and resumes with a refetch', async ({ page }) => {
    await page.clock.install();
    const mock = await installMockBridge(page, { scenario: 'healthy' });
    await page.goto('/#/dashboard');
    await waitReadyWithClock(page);
    await page.clock.runFor(6_000);
    await mock.waitForCall('server_status', 2);
    await setHidden(page, true);
    await page.waitForTimeout(300);
    mock.clear();
    await page.clock.runFor(120_000);
    await page.waitForTimeout(500);
    expect(mock.calls.map((c) => c.method)).toEqual([]);
    await setHidden(page, false);
    await mock.waitForCall('server_status', 1);
    await mock.waitForCall('sync_status', 1);
  });

  test('no duplicate in-flight requests while a call is pending', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'healthy', hang: ['sync_status'] });
    await page.goto('/#/dashboard');
    await mock.waitForCall('sync_status', 1);
    await clickNav(page, 'fiscal');
    await clickNav(page, 'dashboard');
    await clickNav(page, 'license');
    await clickNav(page, 'dashboard');
    await page.waitForTimeout(12_000);
    expect(mock.count('sync_status')).toBe(1);
  });

  test('idle dashboard with the server stopped makes zero DOM mutations over 10 s', async ({ page }) => {
    await page.clock.install();
    const mock = await installMockBridge(page, { scenario: 'stopped' });
    await page.goto('/#/dashboard');
    await waitReadyWithClock(page);
    await page.clock.runFor(200);
    await page.waitForTimeout(500);
    await page.evaluate(() => {
      const w = window as unknown as { __mutations: number };
      w.__mutations = 0;
      new MutationObserver((list) => { w.__mutations += list.length; })
        .observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    });
    const polls = mock.count('server_status');
    for (let i = 0; i < 10; i++) {
      await page.clock.runFor(1_000);
      await page.waitForTimeout(60);
    }
    await page.waitForTimeout(500);
    expect(mock.count('server_status')).toBeGreaterThan(polls);
    expect(await page.evaluate(() => (window as unknown as { __mutations: number }).__mutations)).toBe(0);
  });

  test('running dashboard only mutates the uptime text', async ({ page }) => {
    await page.clock.install();
    await installMockBridge(page, { scenario: 'healthy' });
    await page.goto('/#/dashboard');
    await waitReadyWithClock(page);
    await page.clock.runFor(200);
    await page.waitForTimeout(500);
    await page.evaluate(() => {
      const w = window as unknown as { __outside: string[] };
      w.__outside = [];
      new MutationObserver((list) => {
        for (const m of list) {
          const node = m.target.nodeType === Node.ELEMENT_NODE ? (m.target as Element) : m.target.parentElement;
          if (!node?.closest('[data-uptime]')) w.__outside.push(`${m.type} ${node?.outerHTML.slice(0, 80)}`);
        }
      }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    });
    const before = await page.locator('[data-uptime]').innerText();
    for (let i = 0; i < 10; i++) {
      await page.clock.runFor(1_000);
      await page.waitForTimeout(60);
    }
    await page.waitForTimeout(500);
    expect(await page.locator('[data-uptime]').innerText()).not.toBe(before);
    expect(await page.evaluate(() => (window as unknown as { __outside: string[] }).__outside)).toEqual([]);
  });
});

test.describe('unsaved changes', () => {
  test('config draft survives a language switch and the guard protects it', async ({ page }) => {
    const errors = trackErrors(page);
    const mock = await installMockBridge(page, { scenario: 'healthy' });
    await page.goto('/#/config');
    await waitReady(page);
    const branch = page.locator('#cfg-f-BRANCH_ID');
    await expect(branch).toHaveValue('smartfood-chilonzor');
    await branch.fill('smartfood-yunusobod');
    await expect(page.getByText('1 unsaved changes')).toBeVisible();

    await page.getByRole('radio', { name: 'Русский' }).click();
    await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
    await expect(branch).toHaveValue('smartfood-yunusobod');
    await expect(page.getByText('Несохранённых изменений: 1')).toBeVisible();

    await page.locator('nav.nav a[href="#/logs"]').click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Остаться' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page).toHaveURL(/#\/config$/);
    await expect(branch).toHaveValue('smartfood-yunusobod');
    expect(await page.evaluate(() => window.__alphaHasUnsavedChanges?.())).toBe(true);

    await page.evaluate(() => { window.location.hash = '#/fiscal'; });
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/#\/config$/);
    await dialog.getByRole('button', { name: 'Отменить изменения' }).click();
    await expect(page).toHaveURL(/#\/fiscal$/);
    expect(await page.evaluate(() => window.__alphaHasUnsavedChanges?.())).toBe(false);
    expect(mock.count('save_config')).toBe(0);
    expect(errors).toEqual([]);
  });

  test('config save is disabled until loaded and dirty, then saves the draft', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'healthy', delays: { get_config: 1500 } });
    await page.goto('/#/config');
    const save = page.getByRole('button', { name: 'Save configuration' });
    await expect(save).toBeDisabled();
    await waitReady(page);
    await expect(save).toBeDisabled();
    await page.locator('#cfg-f-PORT').fill('8123');
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.locator('.toast', { hasText: 'Configuration saved' })).toBeVisible();
    const saved = mock.calls.find((c) => c.method === 'save_config');
    // Only the changed key crosses the bridge: an unrelated save must never
    // rewrite staff Telegram recipients or restart the support tunnel.
    expect(saved?.args[0]).toEqual({ PORT: '8123' });
    await expect(save).toBeDisabled();
  });

  test('local audit dirty form survives background polls', async ({ page }) => {
    const mock = await installMockBridge(page, {
      scenario: 'healthy',
      overrides: {
        local_telegram_audit_status: ({ state, call }) => ({
          ok: true, ...state.localAudit, chat_ids: [`-100000000${call}`], configuration_state: 'ready',
          token_configured: true, pending_count: call, retrying_count: 0, worker_alive: true,
        }),
      },
    });
    await page.goto('/#/local-audit');
    await waitReady(page);
    const chats = page.locator('#la-chats');
    await expect(chats).toHaveValue('-1000000000');
    await chats.fill('-1009999999999, @owner_channel');
    const polls = mock.count('local_telegram_audit_status');
    await mock.waitForCall('local_telegram_audit_status', polls + 2, 20_000);
    await expect(chats).toHaveValue('-1009999999999, @owner_channel');
    await page.locator('nav.nav a[href="#/dashboard"]').click();
    await expect(page.getByRole('dialog')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Stay' }).click();
    await page.getByRole('button', { name: 'Save local audit' }).click();
    await expect(page.locator('.toast', { hasText: 'Local Telegram audit saved' })).toBeVisible();
    const saved = mock.calls.find((c) => c.method === 'save_local_telegram_audit');
    expect((saved?.args[0] as Record<string, string>).chat_ids).toBe('-1009999999999, @owner_channel');
  });
});

test.describe('pages', () => {
  test('tests page stops issuing calls after leaving mid-run', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'healthy', delays: { test_server_connection: 1500 } });
    await page.goto('/#/tests');
    await waitReady(page);
    await page.getByRole('button', { name: 'Run all' }).click();
    await mock.waitForCall('test_server_connection', 1);
    await clickNav(page, 'dashboard');
    await page.waitForTimeout(4000);
    for (const method of ['send_mock_sync', 'fetch_mock_sync', 'telegram_test', 'cloud_pull']) {
      expect(mock.count(method), method).toBe(0);
    }
  });

  test('tests page runs sequentially and force pull asks for confirmation', async ({ page }) => {
    const mock = await installMockBridge(page, { scenario: 'offline-cloud' });
    await page.goto('/#/tests');
    await waitReady(page);
    await page.getByRole('button', { name: 'Run all' }).click();
    await expect(page.getByText(/passed/)).toBeVisible();
    await mock.waitForCall('cloud_pull', 1);
    const order = mock.calls.map((c) => c.method).filter((m) => ['test_server_connection', 'send_mock_sync', 'cloud_pull'].includes(m));
    expect(order).toEqual(['test_server_connection', 'send_mock_sync', 'cloud_pull']);

    await page.getByRole('button', { name: 'Replay cloud updates' }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    expect(mock.count('cloud_force_pull')).toBe(0);
    await dialog.getByRole('button', { name: 'Replay cloud updates' }).click();
    await expect(page.locator('.toast', { hasText: 'Replay was saved and will retry automatically.' })).toBeVisible();
  });

  test('logs are virtualized with 5000 entries', async ({ page }) => {
    const errors = trackErrors(page);
    await installMockBridge(page, { scenario: 'big-logs' });
    await page.goto('/#/logs');
    await waitReady(page);
    await expect(page.getByText('Showing 5000')).toBeVisible();
    const rows = await page.locator('.log-row').count();
    expect(rows).toBeGreaterThan(5);
    expect(rows).toBeLessThan(80);
    await page.locator('.vlist').evaluate((el) => { el.scrollTop = 28 * 2500; });
    await expect(page.locator('.log-row').first()).toBeVisible();
    expect(await page.locator('.log-row').count()).toBeLessThan(80);
    await page.locator('.log-row').first().click();
    await expect(page.locator('.log-detail pre')).toBeVisible();
    await page.getByRole('button', { name: /^Errors/ }).click();
    await page.getByRole('searchbox').fill('Push batch 4');
    await expect(page.getByText(/Showing \d+ \/ 5000/)).toBeVisible();
    await sharedAssertions(page, errors, 'big logs');
  });

  test('restart to update follows the updates the desktop app has staged', async ({ browser }) => {
    const legacy = await browser.newPage();
    await installMockBridge(legacy, { scenario: 'update-pending' });
    await legacy.goto('/#/updates');
    await waitReady(legacy);
    await expect(legacy.getByRole('button', { name: 'Install now' })).toBeVisible();
    await expect(legacy.getByRole('button', { name: 'Restart to update' })).toHaveCount(0);
    await legacy.close();

    const shellStatus = (staged: string | null) => (ctx: FixtureContext) => ({
      ...FIXTURES.update_status(ctx),
      managed_by: 'shell', pending: false, available: staged, staged_version: staged,
    });

    const idle = await browser.newPage();
    await installMockBridge(idle, { scenario: 'healthy', tauri: true, overrides: { update_status: shellStatus(null) } });
    await idle.goto('/#/updates');
    await waitReady(idle);
    await expect(idle.getByRole('button', { name: 'Install now' })).toHaveCount(0);
    await expect(idle.getByRole('button', { name: 'Restart to update' })).toBeDisabled();
    await idle.close();

    const shell = await browser.newPage();
    const mock = await installMockBridge(shell, { scenario: 'healthy', tauri: true, overrides: { update_status: shellStatus('1.1.1') } });
    await shell.goto('/#/updates');
    await waitReady(shell);
    await expect(shell.getByText('Version 1.1.1 is downloaded and verified', { exact: false })).toBeVisible();
    const restart = shell.getByRole('button', { name: 'Restart to update' });
    await expect(restart).toBeEnabled();
    await restart.click();
    await mock.waitForCall('restart_to_update');
    await expect(shell.locator('.toast', { hasText: 'Confirm the update' })).toBeVisible();
    await shell.close();
  });

  test('tests that need an unconfigured feature read "Not set up", not FAIL', async ({ page }) => {
    await installMockBridge(page, {
      scenario: 'healthy',
      overrides: {
        telegram_test: () => ({ ok: false, error: 'Not configured', not_configured: true }),
        send_fake_notification: () => ({ ok: false, error: 'chat not found' }),
      },
    });
    await page.goto('/#/tests');
    await waitReady(page);
    const tile = (name: string) => page.locator('.card', { has: page.getByRole('heading', { name }) });
    await tile('Telegram bot').getByRole('button', { name: 'Run' }).click();
    await expect(tile('Telegram bot').getByText('Not set up')).toBeVisible();
    await expect(tile('Telegram bot').locator('.text-danger')).toHaveCount(0);
    await tile('Fake notification').getByRole('button', { name: 'Run' }).click();
    await expect(tile('Fake notification').locator('.text-danger').first()).toBeVisible();
  });

  test('fiscal mode switch is optimistic and rolls back on failure', async ({ page }) => {
    const mock = await installMockBridge(page, {
      scenario: 'healthy',
      overrides: { fiscal_set_mode: () => ({ ok: false, error: 'Live mode requires credentials' }) },
    });
    await page.goto('/#/fiscal');
    await waitReady(page);
    const live = page.getByRole('radio', { name: 'Live' });
    await live.click();
    await expect(page.locator('.toast', { hasText: 'Live mode requires credentials' })).toBeVisible();
    await expect(page.getByRole('radio', { name: 'Mock' })).toHaveAttribute('aria-checked', 'true');
    expect(mock.state.fiscalMode).toBe('mock');
  });

  test('a 403 shows the session-expired banner', async ({ page }) => {
    await installMockBridge(page, { scenario: 'healthy', forbidden: true });
    await page.goto('/#/dashboard');
    const banner = page.locator('.session-banner').getByRole('alert');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Panel session expired');
  });

  test('scenario smoke: every scenario renders every route without errors', async ({ browser }) => {
    test.setTimeout(180_000);
    expect(initialState('offline-cloud').running).toBe(true);
    for (const scenario of ['stopped', 'error', 'unregistered', 'offline-cloud', 'update-pending', 'empty'] as const) {
      const page = await browser.newPage();
      const errors = trackErrors(page);
      await installMockBridge(page, { scenario });
      await page.goto('/#/dashboard');
      for (const route of ROUTES) {
        await openRoute(page, route);
        await sharedAssertions(page, errors, `${scenario} ${route}`);
      }
      await page.close();
    }
  });
});

test.describe('performance', () => {
  test('initial JS stays under budget and other pages load lazily', async ({ page }) => {
    const scripts = new Map<string, number>();
    page.on('response', async (response) => {
      const url = response.url();
      if (url.endsWith('.js')) scripts.set(url.split('/').pop()!, (await response.body()).length);
    });
    await installMockBridge(page, { scenario: 'healthy', prefs: { lang: 'en', theme: 'light' } });
    await page.goto('/#/dashboard');
    await waitReady(page);
    await page.waitForLoadState('networkidle');
    const names = [...scripts.keys()];
    for (const lazy of ['Config', 'Logs', 'Tests', 'License', 'LocalAudit', 'Fiscal', 'Updates', 'uz-', 'ru-']) {
      expect(names.some((n) => n.startsWith(lazy)), `${lazy} must not load on first paint`).toBe(false);
    }
    const initial = [...scripts.entries()].filter(([n]) => !n.startsWith('Observability')).reduce((sum, [, size]) => sum + size, 0);
    expect(initial).toBeLessThanOrEqual(70_000);
  });
});
