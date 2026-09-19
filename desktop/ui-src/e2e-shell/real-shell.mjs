// Drive the real installed Alpha POS window (WebView2) over CDP on Windows CI.
//
// Start the app with WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222,
// then: node e2e-shell/real-shell.mjs [out-dir]
// Fails on page errors, console errors, failed control calls or error panels.
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const out = process.argv[2] || 'shell-e2e';
fs.mkdirSync(out, { recursive: true });
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const problems = [];
const report = { problems, steps: [] };
const step = (name, extra = {}) => { report.steps.push({ name, at: new Date().toISOString(), ...extra }); console.log(`- ${name}`); };

let browser;
for (let i = 0; i < 90 && !browser; i++) {
  try { browser = await chromium.connectOverCDP('http://127.0.0.1:9222'); } catch { await sleep(2000); }
}
if (!browser) throw new Error('WebView2 debugging endpoint never came up');
step('connected to WebView2');

// The panel window opens once the backend serves (or after the splash budget).
let page;
for (let i = 0; i < 300 && !page; i++) {
  for (const context of browser.contexts()) {
    for (const candidate of context.pages()) {
      if (/^http:\/\/127\.0\.0\.1:\d+\//.test(candidate.url())) page = candidate;
    }
  }
  if (!page) await sleep(1000);
}
if (!page) throw new Error('the panel window never opened');
step('panel window found', { url: page.url().replace(/\?.*$/, '') });

let where = 'reload';
page.on('console', (m) => { if (m.type() === 'error') problems.push({ where, kind: 'console', text: m.text() }); });
page.on('pageerror', (e) => problems.push({ where, kind: 'pageerror', text: e.message }));
let apiCalls = 0;
page.on('response', async (r) => {
  if (!r.url().includes('/api/')) return;
  apiCalls += 1;
  if (r.status() >= 400) problems.push({ where, kind: 'http', text: `${r.status()} ${r.url().split('/api/')[1]}` });
});
await page.reload();
await page.locator('h1').waitFor({ timeout: 60000 });
step('panel loaded', { tauri: await page.evaluate(() => !!window.__TAURI_INTERNALS__) });

where = 'dashboard';
await page.getByText(/Server running|Сервер работает|Server ishlamoqda/).first().waitFor({ timeout: 240000 });
await page.waitForTimeout(5000);
await page.screenshot({ path: path.join(out, 'dashboard.png'), fullPage: true });
step('POS server running');

const errorPanels = async () => (await page.locator('.panel-state[role=alert]:visible').allInnerTexts()).map((s) => s.trim());
for (const route of ['license', 'local-audit', 'config', 'tests', 'fiscal', 'logs', 'updates', 'dashboard']) {
  where = route;
  await page.evaluate((r) => { window.location.hash = `#/${r}`; }, route);
  await page.locator('h1').waitFor({ timeout: 30000 });
  await page.waitForTimeout(2500);
  for (const text of await errorPanels()) problems.push({ where, kind: 'error-panel', text });
  await page.screenshot({ path: path.join(out, `${route}.png`), fullPage: true });
}
step('every page opened');

where = 'updates-check';
await page.evaluate(() => { window.location.hash = '#/updates'; });
await page.getByRole('button', { name: /check now/i }).click();
await page.locator('.toast').first().waitFor({ timeout: 15000 });
step('update check requested', { toast: (await page.locator('.toast').first().innerText()).trim() });

report.apiCalls = apiCalls;
if (apiCalls === 0) problems.push({ where: 'transport', kind: 'transport', text: 'no same-origin /api calls were made' });
fs.writeFileSync(path.join(out, 'report.json'), JSON.stringify(report, null, 2));
await browser.close().catch(() => undefined);
console.log(JSON.stringify(report, null, 2));
if (problems.length) {
  console.error(`${problems.length} problem(s) in the real shell`);
  process.exit(1);
}
