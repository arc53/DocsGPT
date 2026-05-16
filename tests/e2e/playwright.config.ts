// No `webServer` block by design — service orchestration (Flask, Celery, Vite,
// mock LLM, Postgres reset) is handled by `scripts/e2e/up.sh` and
// `scripts/e2e/down.sh`. Playwright's built-in `webServer` can only manage one
// process and would fight with the four-service native setup this suite needs.
// See `e2e-plan.md` → "Foundation" → P0-A for the orchestration
// contract.

import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './specs',

  // Serialize everything: we TRUNCATE Postgres between tests, so parallel
  // workers would clobber each other's state.
  fullyParallel: false,
  workers: 1,

  retries: 1,
  // Local-only suite — allow `.only` during development.
  forbidOnly: false,

  // 60s: many specs hit the (stubbed) streaming LLM path end-to-end.
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },

  reporter: [
    ['html', { open: 'never' }],
    ['list'],
  ],

  use: {
    baseURL: 'http://127.0.0.1:5179',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
