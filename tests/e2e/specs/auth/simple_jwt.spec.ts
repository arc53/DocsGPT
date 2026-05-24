/**
 * P1-C · simple_jwt auth flow.
 *
 * Covers e2e-plan.md §7.3: with `AUTH_TYPE=simple_jwt` the backend does NOT
 * issue tokens — the frontend shows `JWTModal`, the user pastes a
 * pre-shared token, we save it, the modal closes, and the app is authed.
 *
 * HOW TO RUN THIS SPEC
 * --------------------
 * The e2e stack defaults to `AUTH_TYPE=session_jwt` (see
 * `scripts/e2e/env.sh`). Only one backend mode can be live per suite run,
 * so this spec self-skips unless the harness is explicitly in simple_jwt
 * mode. To run it:
 *
 *   1. Override the auth type for the backend: either edit `env.sh`
 *      temporarily to `AUTH_TYPE=simple_jwt` OR run
 *      `AUTH_TYPE=simple_jwt scripts/e2e/up.sh` (env passthrough).
 *   2. Also export `E2E_AUTH_MODE=simple_jwt` so this spec un-skips:
 *      `E2E_AUTH_MODE=simple_jwt npm run e2e`.
 *   3. The companion spec `session_jwt.spec.ts` will no-op cleanly in
 *      simple_jwt mode because its token bootstrap tolerates either path.
 *      (`isolation.spec.ts` runs fine in either mode — the isolation
 *      check is orthogonal to which mode is active.)
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { signJwt } from '../../helpers/auth.js';
import { getUserRow } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const SIMPLE_JWT_SUB = 'local';

test.describe('auth · simple_jwt', () => {
  test.skip(
    process.env.E2E_AUTH_MODE !== 'simple_jwt',
    'Only runs when the backend is booted with AUTH_TYPE=simple_jwt. '
      + 'Re-run with `E2E_AUTH_MODE=simple_jwt AUTH_TYPE=simple_jwt npm run e2e`.',
  );

  test.beforeEach(async () => {
    await resetDb();
  });

  test('simple_jwt: JWTModal accepts a token, closes, and the app becomes authed', async ({
    browser,
  }) => {
    // IMPORTANT: do NOT inject a token via newUserContext — the point of
    // this spec is to exercise the modal flow. Use a plain context.
    const context = await browser.newContext();

    try {
      const page = await context.newPage();

      // Matches application/app.py:62-66 — simple_jwt mints a fixed
      // `{sub: 'local'}` JWT server-side; any client token must decode to
      // the same shape for /auth middleware to accept it.
      const token = signJwt(SIMPLE_JWT_SUB);

      await page.goto('/');

      const modal = page.getByTestId('jwt-modal');
      await modal.waitFor({ state: 'visible' });

      await page.getByTestId('jwt-token-input').fill(token);
      await page.getByTestId('jwt-token-submit').click();

      await modal.waitFor({ state: 'hidden' });

      // Main UI now rendered — same resilient selector as session_jwt.spec.
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible();

      // Token round-trip: exactly what we submitted is what's stored.
      const storedToken = await page.evaluate(() =>
        window.localStorage.getItem('authToken'),
      );
      expect(storedToken).toBe(token);

      // Auth plumbing end-to-end: hit a user route with the same token and
      // assert the users row is upserted for sub=local.
      const api = await authedRequest(playwright, token);
      try {
        const res = await api.get('/api/get_prompts');
        expect(res.status()).toBe(200);

        const userRow = await getUserRow(SIMPLE_JWT_SUB);
        expect(userRow).not.toBeNull();
        expect(userRow?.user_id).toBe(SIMPLE_JWT_SUB);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });
});
