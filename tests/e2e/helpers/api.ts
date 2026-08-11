/**
 * Pre-authenticated Playwright APIRequestContext pointed at the e2e Flask.
 */

import type { APIRequestContext } from '@playwright/test';

/**
 * Build an APIRequestContext pre-authenticated with `token`, base-URL'd at the
 * e2e Flask app (default 127.0.0.1:7099). Specs call `.get()/.post()/.dispose()`
 * directly on the returned context; remember to `dispose()` in `afterEach`.
 */
export async function authedRequest(
  playwright: typeof import('@playwright/test'),
  token: string,
): Promise<APIRequestContext> {
  const baseURL = process.env.API_URL ?? 'http://127.0.0.1:7099';
  return playwright.request.newContext({
    baseURL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
  });
}
