import { expect, type Page } from '@playwright/test';

export const ROUTES = ['dashboard', 'license', 'local-audit', 'config', 'tests', 'fiscal', 'logs', 'updates'] as const;
export type Route = (typeof ROUTES)[number];

const RAW_KEY = /\b(?:nav|common|dash|obs|lic|audit|cfg|tests|fis|upd|log|sync|la|chip|phase|theme|session|time)\.[a-z][A-Za-z0-9]+\b/;

export function trackErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(`console: ${message.text()}`);
  });
  page.on('pageerror', (error) => errors.push(`pageerror: ${error.message}`));
  return errors;
}

export async function waitReady(page: Page): Promise<void> {
  await expect(page.locator('main .page')).toBeVisible();
  await expect(page.locator('main .skeleton')).toHaveCount(0, { timeout: 10_000 });
}

/**
 * With page.clock installed, Preact effects (scheduled via rAF/timeout) only
 * run when fake time advances. Advance in small steps (far below any poll
 * interval) until the page has rendered its data.
 */
export async function waitReadyWithClock(page: Page): Promise<void> {
  await expect(page.locator('main')).toBeVisible();
  for (let i = 0; i < 60; i++) {
    await page.clock.runFor(40);
    const ready = await page.evaluate(() => !!document.querySelector('main .page') && !document.querySelector('main .skeleton'));
    if (ready) return;
    await page.waitForTimeout(40);
  }
  await expect(page.locator('main .skeleton')).toHaveCount(0, { timeout: 1 });
}

export async function openRoute(page: Page, route: Route): Promise<void> {
  if (!page.url().includes('127.0.0.1')) {
    await page.goto(`/#/${route}`);
  } else {
    await page.evaluate((r) => { window.location.hash = `#/${r}`; }, route);
  }
  await expect(page).toHaveURL(new RegExp(`#/${route}$`));
  await waitReady(page);
}

/** Assertions every page must satisfy in every language / theme / size. */
export async function sharedAssertions(page: Page, errors: string[], label: string): Promise<void> {
  expect(errors, `${label}: console/page errors`).toEqual([]);

  await expect(page.locator('h1')).toBeVisible();
  const h1 = (await page.locator('h1').first().innerText()).trim();
  expect(h1.length, `${label}: h1 text`).toBeGreaterThan(0);

  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    const main = document.querySelector('main')!;
    return {
      doc: doc.scrollWidth - doc.clientWidth,
      main: main.scrollWidth - main.clientWidth,
    };
  });
  expect(overflow.doc, `${label}: document horizontal overflow`).toBeLessThanOrEqual(1);
  expect(overflow.main, `${label}: main horizontal overflow`).toBeLessThanOrEqual(1);

  const text = await page.locator('body').innerText();
  const rawKey = RAW_KEY.exec(text);
  expect(rawKey?.[0] ?? null, `${label}: raw i18n key visible`).toBeNull();

  const unnamed = await page.evaluate(() => {
    const nameOf = (el: Element) => {
      const aria = el.getAttribute('aria-label');
      if (aria && aria.trim()) return aria.trim();
      const labelledBy = el.getAttribute('aria-labelledby');
      if (labelledBy) {
        const t = labelledBy.split(/\s+/).map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
        if (t) return t;
      }
      const own = (el.textContent || '').trim();
      if (own) return own;
      return (el.getAttribute('title') || '').trim();
    };
    const visible = (el: Element) => {
      const rect = (el as HTMLElement).getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };
    return Array.from(document.querySelectorAll('button, [role="switch"], [role="radio"], a[href], input:not([type="hidden"]), select, textarea'))
      .filter(visible)
      .filter((el) => {
        const tag = el.tagName.toLowerCase();
        if (tag === 'input' || tag === 'select' || tag === 'textarea') {
          const id = el.id;
          const hasLabel = !!(id && document.querySelector(`label[for="${id}"]`)) || !!el.getAttribute('aria-label');
          return !hasLabel;
        }
        return !nameOf(el);
      })
      .map((el) => el.outerHTML.slice(0, 120));
  });
  expect(unnamed, `${label}: controls without accessible names`).toEqual([]);
}
