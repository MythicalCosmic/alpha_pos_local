import { defineConfig, devices } from '@playwright/test';

// Runs against `vite preview` of the committed production build (../ui) with a
// mocked bridge (e2e/mock-bridge.ts). Intended to run inside
// mcr.microsoft.com/playwright:v1.60.0-noble.
export default defineConfig({
  testDir: './e2e',
  outputDir: './test-results',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.PW_WORKERS ? Number(process.env.PW_WORKERS) : undefined,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 7_500 },
  use: {
    baseURL: 'http://127.0.0.1:4173',
    ...devices['Desktop Chrome'],
    viewport: { width: 1366, height: 768 },
    trace: 'off',
  },
  webServer: {
    command: 'node node_modules/vite/bin/vite.js preview --port 4173 --strictPort --host 127.0.0.1',
    url: 'http://127.0.0.1:4173/',
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
