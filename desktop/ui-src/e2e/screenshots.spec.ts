import path from 'node:path';
import { test } from '@playwright/test';
import type { Scenario } from './fixtures/bridge-fixtures';
import { installMockBridge } from './mock-bridge';
import { waitReady } from './support';

// Documentation screenshots; runs only when SHOT_DIR is set.
const SHOT_DIR = process.env.SHOT_DIR;

const SHOTS: Array<{ name: string; route: string; scenario: Scenario; theme: string; lang: string; width: number; height: number; fullPage?: boolean }> = [
  { name: 'dashboard-light-1366', route: 'dashboard', scenario: 'healthy', theme: 'light', lang: 'en', width: 1366, height: 768, fullPage: true },
  { name: 'dashboard-dark-1366', route: 'dashboard', scenario: 'offline-cloud', theme: 'dark', lang: 'en', width: 1366, height: 768, fullPage: true },
  { name: 'dashboard-booting-900-ru', route: 'dashboard', scenario: 'booting', theme: 'light', lang: 'ru', width: 900, height: 640 },
  { name: 'config-light-1366', route: 'config', scenario: 'healthy', theme: 'light', lang: 'en', width: 1366, height: 768 },
  { name: 'logs-dark-1366', route: 'logs', scenario: 'big-logs', theme: 'dark', lang: 'en', width: 1366, height: 768 },
  { name: 'local-audit-uz-900', route: 'local-audit', scenario: 'healthy', theme: 'light', lang: 'uz', width: 900, height: 640 },
  { name: 'updates-pending-1366', route: 'updates', scenario: 'update-pending', theme: 'light', lang: 'en', width: 1366, height: 768 },
];

for (const shot of SHOTS) {
  test(`screenshot ${shot.name}`, async ({ page }) => {
    test.skip(!SHOT_DIR, 'SHOT_DIR not set');
    await page.setViewportSize({ width: shot.width, height: shot.height });
    await installMockBridge(page, { scenario: shot.scenario, prefs: { theme: shot.theme, lang: shot.lang } });
    await page.goto(`/#/${shot.route}`);
    if (shot.scenario === 'booting') await page.waitForTimeout(800);
    else await waitReady(page);
    if (shot.route === 'logs') await page.locator('.log-row').nth(4).click();
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SHOT_DIR!, `${shot.name}.png`), fullPage: shot.fullPage });
  });
}
