import { test } from '@playwright/test';
import { installMockBridge } from './mock-bridge';
import { openRoute, ROUTES, sharedAssertions, trackErrors } from './support';

const LANGS = ['en', 'uz', 'ru'] as const;
const THEMES = ['light', 'dark'] as const;
const VIEWPORTS = [
  { width: 900, height: 640 },
  { width: 1366, height: 768 },
] as const;

for (const lang of LANGS) {
  for (const theme of THEMES) {
    for (const viewport of VIEWPORTS) {
      test(`all routes · ${lang} · ${theme} · ${viewport.width}x${viewport.height}`, async ({ page }) => {
        await page.setViewportSize(viewport);
        const errors = trackErrors(page);
        await installMockBridge(page, { scenario: 'healthy', prefs: { theme, lang } });
        await page.goto('/#/dashboard');
        for (const route of ROUTES) {
          await openRoute(page, route);
          await page.waitForFunction(([l, th]) => document.documentElement.lang === l && document.documentElement.dataset.theme === th, [lang, theme]);
          await sharedAssertions(page, errors, `${route} ${lang} ${theme} ${viewport.width}`);
        }
      });
    }
  }
}
