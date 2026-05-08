/**
 * Phase 1 helper — see e2e-plan.md §P1-B.
 * JWT signing + per-test BrowserContext seeding for DocsGPT e2e.
 */

import { randomUUID } from 'node:crypto';
import jwt from 'jsonwebtoken';
import type { Browser, BrowserContext } from '@playwright/test';

/**
 * Default secret mirrors Appendix A of e2e-plan.md. Overridable for negative
 * tests (e.g. asserting a wrong-secret token is rejected). `process.env` is
 * read lazily so spec-level `env` overrides still take effect.
 */
function defaultSecret(): string {
  return process.env.JWT_SECRET_KEY ?? 'e2e-fixed-secret-never-use-in-prod';
}

/**
 * Sign an HS256 JWT matching the backend's expected shape. No `exp` claim —
 * matches application/app.py:62-66 which issues tokens with only `{sub}`.
 */
export function signJwt(sub: string, secret?: string): string {
  return jwt.sign({ sub }, secret ?? defaultSecret(), { algorithm: 'HS256' });
}

/**
 * Playwright `addInitScript` helper: seeds `localStorage.authToken` BEFORE the
 * first navigation, so the frontend's auth bootstrap picks it up on load
 * instead of prompting for one.
 */
export async function injectTokenBeforeNavigation(
  context: BrowserContext,
  token: string,
): Promise<void> {
  await context.addInitScript((t: string) => {
    try {
      window.localStorage.setItem('authToken', t);
    } catch {
      // localStorage may be unavailable on about:blank-style pages; the first
      // real navigation will re-run this init script with a valid origin.
    }
  }, token);
}

/**
 * Create a fresh BrowserContext with a freshly-signed JWT already injected
 * into localStorage. Returns the context plus the sub/token so specs can
 * assert against DB rows keyed on `users.user_id = sub`.
 */
export async function newUserContext(
  browser: Browser,
  opts?: { sub?: string },
): Promise<{ context: BrowserContext; sub: string; token: string }> {
  const sub = opts?.sub ?? randomUUID();
  const token = signJwt(sub);
  const context = await browser.newContext();
  await injectTokenBeforeNavigation(context, token);
  return { context, sub, token };
}
