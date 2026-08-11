/**
 * OIDC SSO auth flow (AUTH_TYPE=oidc).
 *
 * Covers the backend-driven Authorization Code + PKCE flow: the SPA
 * auto-redirects to `/api/auth/oidc/login`, the IdP (a local mock —
 * scripts/e2e/mock_oidc_idp.py — spawned by this spec) auto-approves, the
 * callback mints a local HS256 session JWT and hands it to the SPA via a
 * single-use `#oidc_code=` fragment, which the SPA exchanges and stores as
 * `localStorage.authToken`.
 *
 * HOW TO RUN THIS SPEC
 * --------------------
 * Only one backend auth mode can be live per suite run, so this spec
 * self-skips unless the harness is in oidc mode:
 *
 *   1. Boot the stack in oidc mode: `AUTH_TYPE=oidc scripts/e2e/up.sh`
 *      (env.sh fills in OIDC_ISSUER/OIDC_CLIENT_ID/OIDC_FRONTEND_URL
 *      defaults pointing at the mock IdP on :7999).
 *   2. Un-skip and run: `E2E_AUTH_MODE=oidc npx playwright test specs/auth/oidc.spec.ts`.
 *   3. The mock IdP itself is started/stopped by this spec's beforeAll /
 *      afterAll — no extra terminal needed.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;
import jwt from 'jsonwebtoken';

import { authedRequest } from '../../helpers/api.js';
import { getUserRow } from '../../helpers/db.js';
import { MOCK_OIDC_ISSUER, startMockIdp } from '../../helpers/oidc.js';
import { resetDb } from '../../helpers/reset.js';

const OIDC_SUB = 'mock-oidc-user';
const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

test.describe('auth · oidc', () => {
  test.skip(
    process.env.E2E_AUTH_MODE !== 'oidc',
    'Only runs when the backend is booted with AUTH_TYPE=oidc. '
      + 'Re-run with `AUTH_TYPE=oidc scripts/e2e/up.sh` then '
      + '`E2E_AUTH_MODE=oidc npx playwright test specs/auth/oidc.spec.ts`.',
  );

  let idp: { stop: () => void };

  test.beforeAll(async () => {
    idp = await startMockIdp();
  });

  test.afterAll(() => {
    idp?.stop();
  });

  test.beforeEach(async () => {
    await resetDb();
  });

  test('oidc: full browser login — redirect to IdP, back, session stored, API authed', async ({
    browser,
  }) => {
    // Plain context: no token injection — the whole point is the redirect flow.
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      await page.goto('/');

      // SPA discovers oidc mode, bounces through the IdP, and lands back
      // authed — the nav chrome appearing means the loop completed.
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible({ timeout: 20_000 });

      const storedToken = await page.evaluate(() =>
        window.localStorage.getItem('authToken'),
      );
      expect(storedToken).toBeTruthy();
      const decoded = jwt.decode(storedToken as string) as Record<string, unknown>;
      expect(decoded.sub).toBe(OIDC_SUB);
      expect(decoded.email).toBe('mock-oidc-user@example.com');
      expect(typeof decoded.exp).toBe('number');

      // The handoff fragment must not linger in the address bar.
      expect(page.url()).not.toContain('oidc_code');

      // Minted session works against the API and upserts the users row.
      const api = await authedRequest(playwright, storedToken as string);
      try {
        const res = await api.get('/api/get_prompts');
        expect(res.status()).toBe(200);
        const userRow = await getUserRow(OIDC_SUB);
        expect(userRow).not.toBeNull();
        expect(userRow?.user_id).toBe(OIDC_SUB);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });

  test('oidc: sign out hits the IdP end-session and re-login works', async ({
    browser,
  }) => {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();

      const endSessionRequests: string[] = [];
      page.on('request', (req) => {
        if (req.url().startsWith(`${MOCK_OIDC_ISSUER}/end-session`)) {
          endSessionRequests.push(req.url());
        }
      });

      await page.goto('/');
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible({ timeout: 20_000 });

      await page.getByTestId('oidc-signout').click();

      // Logout chain: backend /logout → IdP end-session → back to the app,
      // which (mock IdP auto-approves) walks straight through a fresh login.
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible({ timeout: 20_000 });

      expect(endSessionRequests.length).toBeGreaterThan(0);
      expect(endSessionRequests[0]).toContain('post_logout_redirect_uri');

      const tokenAfter = await page.evaluate(() =>
        window.localStorage.getItem('authToken'),
      );
      expect(tokenAfter).toBeTruthy();
      expect((jwt.decode(tokenAfter as string) as Record<string, unknown>).sub).toBe(
        OIDC_SUB,
      );
    } finally {
      await context.close();
    }
  });

  test('oidc: handoff code is single-use (API-level redirect walk)', async () => {
    const api = await playwright.request.newContext({ baseURL: API_URL });
    try {
      const login = await api.get('/api/auth/oidc/login', { maxRedirects: 0 });
      expect(login.status()).toBe(302);
      const authorizeUrl = login.headers()['location'];
      expect(authorizeUrl).toContain(`${MOCK_OIDC_ISSUER}/authorize`);
      expect(authorizeUrl).toContain('code_challenge_method=S256');

      const authorize = await api.get(authorizeUrl, { maxRedirects: 0 });
      expect(authorize.status()).toBe(302);
      const callbackUrl = authorize.headers()['location'];
      expect(callbackUrl).toContain('/api/auth/oidc/callback');

      const callback = await api.get(callbackUrl, { maxRedirects: 0 });
      expect(callback.status()).toBe(302);
      const frontendUrl = callback.headers()['location'];
      expect(frontendUrl).toContain('#oidc_code=');
      const code = frontendUrl.split('#oidc_code=')[1];

      const first = await api.post('/api/auth/oidc/token', {
        data: { code },
      });
      expect(first.status()).toBe(200);
      const { token } = await first.json();
      expect((jwt.decode(token) as Record<string, unknown>).sub).toBe(OIDC_SUB);

      const replay = await api.post('/api/auth/oidc/token', {
        data: { code },
      });
      expect(replay.status()).toBe(401);
    } finally {
      await api.dispose();
    }
  });
});
