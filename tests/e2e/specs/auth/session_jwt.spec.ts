/**
 * Phase 1 — P1-C · session_jwt auth flow.
 *
 * Covers e2e-plan.md §7.2: with `AUTH_TYPE=session_jwt` the backend issues a
 * fresh token via `/api/generate_token` on first load, the frontend stashes
 * it in localStorage, the main UI renders, and an authed call to a user
 * route upserts a `users` row via `ensure_user_doc`.
 *
 * Single-boot strategy: this spec assumes the backend was launched with
 * `AUTH_TYPE=session_jwt` (the default set by `scripts/e2e/env.sh`). It is
 * tolerant of two startup paths because we pre-inject a JWT into
 * `localStorage` via `newUserContext`:
 *   1. The app sees the injected token on boot and skips /api/generate_token.
 *   2. The app (for any reason) still calls /api/generate_token and overwrites.
 * Either outcome is acceptable — we only assert the invariants that must hold
 * once the shell is up: localStorage has a non-empty authToken AND the nav
 * chrome is rendered.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { getUserRow } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

test.describe('auth · session_jwt', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('session_jwt: app bootstraps with a token and upserts users row on first authed call', async ({
    browser,
  }) => {
    const sub = 'e2e-session-jwt-user';
    const { context, token } = await newUserContext(browser, { sub });

    try {
      const page = await context.newPage();

      // Race /api/generate_token vs the first paint. Either outcome is fine —
      // the injected token makes the /generate_token call optional. We wait
      // for whichever completes first, then proceed to the real assertions.
      const generateTokenRace = page
        .waitForResponse(
          (r) => r.url().includes('/api/generate_token') && r.status() === 200,
          { timeout: 8_000 },
        )
        .catch(() => null);

      await page.goto('/');
      await generateTokenRace;

      // Main UI rendered. `Spinner` is shown while `isAuthLoading` — once we
      // see the nav chrome, the auth bootstrap has resolved. "New Chat" is
      // the English-default label of the primary NavLink in Navigation.tsx
      // and is visible on both desktop and mobile layouts.
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible();

      // localStorage has a non-empty authToken — tolerates both the "reuse
      // injected token" path and the "app issued a new token" path.
      const storedToken = await page.evaluate(() =>
        window.localStorage.getItem('authToken'),
      );
      expect(storedToken).toBeTruthy();
      expect(typeof storedToken).toBe('string');
      expect((storedToken ?? '').length).toBeGreaterThan(0);

      // `ensure_user_doc` only fires on an authed user-route hit, not on the
      // initial shell load. Hit the simplest user route and then assert the
      // `users` row has been upserted for this sub.
      //
      // If the app re-issued a token via /generate_token, the stored token
      // will have a different `sub` than the one we injected. In that case
      // there's no way to predict the new `sub` — so we use OUR injected
      // token directly against the backend to guarantee we're asserting
      // against the JWT we control.
      const api = await authedRequest(playwright, token);
      try {
        const res = await api.get('/api/get_prompts');
        expect(res.status()).toBe(200);

        const userRow = await getUserRow(sub);
        expect(userRow).not.toBeNull();
        expect(userRow?.user_id).toBe(sub);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });
});
