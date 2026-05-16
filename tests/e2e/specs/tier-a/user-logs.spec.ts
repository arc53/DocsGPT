/**
 * P2-06 · User activity logs viewer.
 *
 * Reads from the append-only `user_logs` table via the
 * `POST /api/get_user_logs` endpoint (the call the UI issues from
 * `frontend/src/settings/Logs.tsx` → `userService.getLogs`). Each log row is
 * written server-side by `complete_stream` in
 * `application/api/answer/routes/base.py:460-466` — so the "seed" for these
 * tests is a real `POST /stream` exchange (drained fully so the generator
 * reaches the insert statement before we assert).
 *
 * // Silent-break covered: find_by_api_key filter on data->>'api_key'
 *    returns rows. The repo-side `UserLogsRepository.find_by_api_key`
 *    (application/storage/db/repositories/user_logs.py:86-115) filters rows
 *    via `WHERE data->>'api_key' = :api_key`. If a refactor ever promoted
 *    `api_key` to a top-level column on `user_logs` (or renamed the JSONB
 *    key), the JSONB text-extractor would return NULL for every row and
 *    the per-agent log view would silently render empty — the UI would
 *    look like it "lost" every historical log for that agent without any
 *    error surfacing. The `Silent-break: filter by api_key` test proves
 *    the end-to-end path (publish agent → `/stream` with `api_key` →
 *    `/api/get_user_logs?api_key_id=<agent uuid>`) still yields the newly
 *    written row, and doubles up with a direct DB probe on
 *    `data->>'api_key'` for ground-truth sanity.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';
import {
  multipartAuthedRequest,
  publishClassicAgent,
} from '../../helpers/agents.js';

interface GetLogsResponse {
  success: boolean;
  logs: Array<{
    id: string;
    action: string | null;
    level: string | null;
    user: string | null;
    question: string | null;
    sources: unknown;
    retriever_params: unknown;
    timestamp: string | null;
  }>;
  page: number;
  page_size: number;
  has_more: boolean;
}

/**
 * Drive a single `/stream` exchange to completion. Playwright's
 * APIRequestContext buffers the full SSE body into `res.text()` — which
 * means by the time the promise resolves, `complete_stream` has written
 * the `user_logs` row (the insert sits just before the final
 * `data: {"type": "end"}` frame the generator emits).
 */
async function streamOnce(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<void> {
  const res = await api.post('/stream', { data: body });
  expect(res.status()).toBe(200);
  // Fully drain the SSE body so the server-side generator (and the log
  // insert at the tail of it) runs to completion before we move on.
  const text = await res.text();
  // Smoke-check we actually got an SSE "end" frame — otherwise the insert
  // may not have fired and the rest of the assertions would be racing.
  expect(text).toContain('"type": "end"');
}

/**
 * Publish a bare-bones classic agent and return `{ id, key }`. `key` is the
 * agent's API key (the value that lands in `agents.key` and, later, in
 * `user_logs.data->>'api_key'` when a request is made with it).
 *
 * Delegates to the shared `publishClassicAgent` helper — it owns the
 * multipart-context plumbing and the minimum-required-fields contract
 * (name, description, chunks, retriever, prompt_id, source).
 */
async function publishAgent(
  jsonApi: APIRequestContext,
  token: string,
  userId: string,
  name: string,
): Promise<{ id: string; key: string }> {
  const multipartApi = await multipartAuthedRequest(token);
  try {
    const result = await publishClassicAgent(jsonApi, multipartApi, userId, name);
    return { id: result.id, key: result.key };
  } finally {
    await multipartApi.dispose();
  }
}

test.describe('tier-a · user logs', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('user logs populated after a chat action — GET via /api/get_user_logs returns a row with {timestamp, action, question, sources}', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const question = 'e2e-user-logs-smoke question';
      await streamOnce(api, { question, history: '[]' });

      // DB-level sanity — the insert landed on this user.
      const { rows: dbRows } = await pg.query<{ n: string }>(
        'SELECT count(*)::text AS n FROM user_logs WHERE user_id = $1',
        [sub],
      );
      expect(Number(dbRows[0]?.n ?? 0)).toBeGreaterThanOrEqual(1);

      const listRes = await api.post('/api/get_user_logs', {
        data: { page: 1, page_size: 10 },
      });
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as GetLogsResponse;
      expect(listBody.success).toBe(true);
      expect(listBody.page).toBe(1);
      expect(listBody.page_size).toBe(10);
      expect(listBody.logs.length).toBeGreaterThanOrEqual(1);

      // Pick the log row written by our `streamOnce` call (the generator
      // emits `action: "stream_answer"`).
      const ourLog = listBody.logs.find(
        (l) => l.action === 'stream_answer' && l.question === question,
      );
      expect(ourLog).toBeDefined();
      expect(ourLog!.timestamp).toBeTruthy();
      // `sources` is always serialized as part of log_data (empty array
      // when no docs retrieved), so the key must be present — even if the
      // value is an empty list.
      expect(ourLog!.sources).not.toBeUndefined();
      expect(ourLog!.user).toBe(sub);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('pagination — 12 rows, page_size=5 walks through three pages with has_more flipping on the last', async ({
    browser,
  }) => {
    // 12 is deliberate: with page_size=5 we get pages of 5/5/2, exercising
    // both the "full page" and "remainder page" branches of list_paginated.
    const ROWS = 12;
    const PAGE_SIZE = 5;
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      for (let i = 0; i < ROWS; i++) {
        await streamOnce(api, {
          question: `pagination-seed-${i}`,
          history: '[]',
        });
      }

      // DB-level sanity: exactly ROWS log entries for this user. (Each
      // `/stream` call writes exactly one stream_answer row.)
      const { rows: countRows } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM user_logs
         WHERE user_id = $1 AND data->>'action' = 'stream_answer'`,
        [sub],
      );
      expect(Number(countRows[0]?.n ?? 0)).toBe(ROWS);

      // Page 1 — full page, has_more true.
      const page1 = await api.post('/api/get_user_logs', {
        data: { page: 1, page_size: PAGE_SIZE },
      });
      expect(page1.status()).toBe(200);
      const body1 = (await page1.json()) as GetLogsResponse;
      expect(body1.success).toBe(true);
      expect(body1.logs.length).toBe(PAGE_SIZE);
      expect(body1.has_more).toBe(true);

      // Page 2 — full page, still has_more.
      const page2 = await api.post('/api/get_user_logs', {
        data: { page: 2, page_size: PAGE_SIZE },
      });
      expect(page2.status()).toBe(200);
      const body2 = (await page2.json()) as GetLogsResponse;
      expect(body2.logs.length).toBe(PAGE_SIZE);
      expect(body2.has_more).toBe(true);

      // Page 3 — remainder (12 - 10 = 2 rows), has_more false.
      const page3 = await api.post('/api/get_user_logs', {
        data: { page: 3, page_size: PAGE_SIZE },
      });
      expect(page3.status()).toBe(200);
      const body3 = (await page3.json()) as GetLogsResponse;
      expect(body3.logs.length).toBe(ROWS - 2 * PAGE_SIZE);
      expect(body3.has_more).toBe(false);

      // No overlap between pages — the 12 ids returned across pages 1-3
      // should all be distinct.
      const idsAcrossPages = [
        ...body1.logs,
        ...body2.logs,
        ...body3.logs,
      ].map((l) => l.id);
      expect(new Set(idsAcrossPages).size).toBe(ROWS);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('silent-break — filter by api_key_id returns rows written via /stream with api_key', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Publish an agent so it gets a real `agents.key` (draft agents
      // have key = "" and wouldn't exercise the find_by_api_key path).
      const agent = await publishAgent(api, token, sub, 'silent-break-user-logs');

      // One request owner-to-own-agent via the api_key path (the exact
      // call shape widget / external integrations use).
      const question = 'silent-break-find_by_api_key question';
      await streamOnce(api, {
        question,
        history: '[]',
        api_key: agent.key,
      });

      // DB ground truth: the JSONB extractor `data->>'api_key'` finds the
      // row. If the "refactor moved api_key to a top-level column" ever
      // lands, this count drops to zero and the UI view goes silent.
      const { rows: dbHits } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM user_logs
         WHERE data->>'api_key' = $1`,
        [agent.key],
      );
      expect(Number(dbHits[0]?.n ?? 0)).toBeGreaterThanOrEqual(1);

      // UI-facing view: filter by api_key_id (the agent's PG UUID). The
      // route resolves it to `agents.key` via `_resolve_api_key` then
      // dispatches to `find_by_api_key` — same JSONB filter.
      const listRes = await api.post('/api/get_user_logs', {
        data: { api_key_id: agent.id, page: 1, page_size: 10 },
      });
      expect(listRes.status()).toBe(200);
      const listBody = (await listRes.json()) as GetLogsResponse;
      expect(listBody.success).toBe(true);
      expect(listBody.logs.length).toBeGreaterThanOrEqual(1);

      const ourLog = listBody.logs.find(
        (l) => l.action === 'stream_answer' && l.question === question,
      );
      expect(ourLog).toBeDefined();
      expect(ourLog!.user).toBe(sub);

      // Cross-check: the same endpoint with NO api_key_id also lists the
      // row (unfiltered path), so we haven't accidentally proved a
      // filter-only side effect.
      const unfilteredRes = await api.post('/api/get_user_logs', {
        data: { page: 1, page_size: 10 },
      });
      expect(unfilteredRes.status()).toBe(200);
      const unfilteredBody = (await unfilteredRes.json()) as GetLogsResponse;
      expect(
        unfilteredBody.logs.some(
          (l) => l.action === 'stream_answer' && l.question === question,
        ),
      ).toBe(true);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('cross-tenant — user B filtering by user A agent_id cannot see user A logs', async ({
    browser,
  }) => {
    const userA = await newUserContext(browser, { sub: 'e2e-user-logs-a' });
    const userB = await newUserContext(browser, { sub: 'e2e-user-logs-b' });
    const apiA = await authedRequest(playwright, userA.token);
    const apiB = await authedRequest(playwright, userB.token);
    try {
      const agentA = await publishAgent(apiA, userA.token, userA.sub, 'cross-tenant-user-logs');
      const secretQuestion = 'cross-tenant-secret-question';
      await streamOnce(apiA, {
        question: secretQuestion,
        history: '[]',
        api_key: agentA.key,
      });

      // DB ground truth — user A's row is in place.
      const { rows: dbHits } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM user_logs
         WHERE user_id = $1 AND data->>'api_key' = $2`,
        [userA.sub, agentA.key],
      );
      expect(Number(dbHits[0]?.n ?? 0)).toBeGreaterThanOrEqual(1);

      // User B tries to filter by user A's agent_id. `_resolve_api_key`
      // does `AgentsRepository.get_any(agent_id, user=B)` → returns None
      // (the agent belongs to A, so the user_id scoping fails) → the
      // route falls back to `list_paginated(user_id=B)` which returns
      // user B's own logs (empty — B hasn't streamed).
      const bRes = await apiB.post('/api/get_user_logs', {
        data: { api_key_id: agentA.id, page: 1, page_size: 10 },
      });
      expect(bRes.status()).toBe(200);
      const bBody = (await bRes.json()) as GetLogsResponse;
      expect(bBody.success).toBe(true);
      // Critical: B must NOT see A's secret question, regardless of how
      // the route handles an unauthorised api_key_id.
      expect(
        bBody.logs.some((l) => l.question === secretQuestion),
      ).toBe(false);
      // And B's user_id never appears as A's.
      for (const log of bBody.logs) {
        expect(log.user).not.toBe(userA.sub);
      }
    } finally {
      await apiA.dispose();
      await apiB.dispose();
      await userA.context.close();
      await userB.context.close();
    }
  });

  test('page=0 clamping — negative-offset query does not 500, returns a sane response', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      await streamOnce(api, {
        question: 'page-zero-clamp-question',
        history: '[]',
      });

      // page=0 is an edge case the route passes straight into
      // list_paginated: offset becomes (0-1)*page_size = -page_size. On
      // Postgres, a negative OFFSET raises `22023 OFFSET must not be
      // negative`. The route catches the exception and returns 400 — OR,
      // if a future fix clamps `page` to >=1, it returns 200. Either is
      // acceptable here; the hard failure mode we guard against is a
      // 500 / unhandled DB error leaking to the UI.
      const res = await api.post('/api/get_user_logs', {
        data: { page: 0, page_size: 5 },
      });
      expect([200, 400]).toContain(res.status());
      expect(res.status()).not.toBe(500);

      const body = (await res.json()) as { success: boolean };
      // Regardless of outcome the response must be well-formed JSON with
      // a `success` boolean — the UI branches on it.
      expect(typeof body.success).toBe('boolean');
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
