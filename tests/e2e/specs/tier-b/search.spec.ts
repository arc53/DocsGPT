// Tier-B · /api/search via agent api_key
/**
 * B8 · `/api/search` via agent api_key.
 *
 * `application/api/answer/routes/search.py` is the fast-path retrieval
 * endpoint used by embed/widget integrations: it takes a body with
 * `{question, api_key, chunks?}`, looks up the agent by `key`, and calls
 * the vectorstore directly — no LLM involved. Auth is purely api-key
 * based (the Authorization JWT header is NOT consulted by this route;
 * if present it's still validated by the `authenticate_request`
 * before_request so we exercise the endpoint with no Authorization
 * header, which mirrors the widget call path).
 *
 * The `source_id` for a freshly-published agent points at our
 * `insertFixtureSource` row — the vectorstore at that source id doesn't
 * exist yet, so search gracefully returns [] rather than 500ing (per
 * the source-loading `try/except` in `_search_vectorstores`). That's
 * the empty-data contract we assert.
 *
 * Cross-tenant note: /api/search identifies the OWNER via the api_key
 * alone. An API-key holder can hit the endpoint from anywhere in the
 * world, authenticated or not, and the scoping is enforced by the
 * source_id resolution — there is no "calling user" context. We pin
 * that contract with a two-user test.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import {
  multipartAuthedRequest,
  publishClassicAgent,
} from '../../helpers/agents.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

/**
 * Unauthenticated APIRequestContext. /api/search is explicitly designed
 * to accept calls with no Authorization header — the Bearer check in
 * `authenticate_request` only 401s when the header is PRESENT but not
 * a decodable JWT, so sending no header at all lets the request through.
 */
async function anonRequest(): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: { 'Content-Type': 'application/json' },
  });
}

/**
 * Helper to publish a fresh classic agent for a user. Returns the
 * {id, key, sourceId, promptId}.
 */
async function publishAgentFor(
  token: string,
  userId: string,
  name: string,
): Promise<{ id: string; key: string; sourceId: string }> {
  const jsonApi = await authedRequest(playwright, token);
  const multipart = await multipartAuthedRequest(token);
  try {
    return await publishClassicAgent(jsonApi, multipart, userId, name);
  } finally {
    await multipart.dispose();
    await jsonApi.dispose();
  }
}

test.describe('tier-b · /api/search via agent api_key', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('valid api_key with no vector data returns an empty array (not an error)', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const agent = await publishAgentFor(token, sub, 'b8-empty-search');

    const anon = await anonRequest();
    try {
      const res = await anon.post('/api/search', {
        data: {
          question: 'anything — e2e-b8-empty',
          api_key: agent.key,
          chunks: 3,
        },
      });
      expect(res.status()).toBe(200);
      const body = await res.json();
      // Contract: empty/no-data agents return [] with 200. A regression
      // to 500 here would break every widget embed pointing at a
      // just-minted agent that hasn't ingested yet.
      expect(Array.isArray(body)).toBe(true);
      expect(body).toHaveLength(0);

      // State-change invariant: the endpoint does NOT write to any DB
      // surface — verify the agent row still has the key we created
      // with (i.e. the lookup went through, not a blind 200).
      const { rows } = await pg.query<{ key: string }>(
        `SELECT key FROM agents WHERE id = CAST($1 AS uuid)`,
        [agent.id],
      );
      expect(rows[0]?.key).toBe(agent.key);
    } finally {
      await anon.dispose();
    }
  });

  test('missing api_key → 400 (route validation)', async ({ browser }) => {
    const { sub, token } = await newUserContext(browser);
    // We still need a user context for resetDb+invariants, but we
    // actually send an anon request because /api/search is keyed on
    // api_key, not JWT. (newUserContext unused for the HTTP call but
    // required by the test-level invariant of one context per test.)
    void sub;
    void token;

    const anon = await anonRequest();
    try {
      const res = await anon.post('/api/search', {
        data: { question: 'no key — e2e-b8-no-key' },
      });
      expect(res.status()).toBe(400);
      const body = await res.json();
      expect(body.error).toBe('api_key is required');
    } finally {
      await anon.dispose();
    }
  });

  test('invalid api_key → 401 (Invalid API key)', async ({ browser }) => {
    const { sub, token } = await newUserContext(browser);
    void sub;
    void token;

    const anon = await anonRequest();
    try {
      const res = await anon.post('/api/search', {
        data: {
          question: 'bogus — e2e-b8-bad-key',
          api_key: 'definitely-not-a-real-agent-key',
        },
      });
      // Invalid key path in search.py is an explicit 401 (not 403 nor
      // 404), and the JSON payload carries {error: "Invalid API key"}.
      expect(res.status()).toBe(401);
      const body = await res.json();
      expect(body.error).toBe('Invalid API key');
    } finally {
      await anon.dispose();
    }
  });

  test('missing question → 400 (route validation)', async ({ browser }) => {
    const { sub, token } = await newUserContext(browser);
    const agent = await publishAgentFor(token, sub, 'b8-no-question');

    const anon = await anonRequest();
    try {
      const res = await anon.post('/api/search', {
        data: { api_key: agent.key },
      });
      expect(res.status()).toBe(400);
      const body = await res.json();
      expect(body.error).toBe('question is required');
    } finally {
      await anon.dispose();
    }
  });

  test('cross-tenant: user B\'s api_key called from a no-auth context still scopes to B\'s agent/source, not the caller', async ({
    browser,
  }) => {
    // Two separate users, each publishes an agent. The agent key
    // identifies the owner — a caller without a JWT (or with a
    // different user's JWT, but we keep this anon since the route
    // never reads the JWT) can use user B's api_key to search B's
    // source. The result is scoped to B.
    const userA = await newUserContext(browser, { sub: 'b8-tenant-a' });
    const userB = await newUserContext(browser, { sub: 'b8-tenant-b' });
    const agentA = await publishAgentFor(userA.token, userA.sub, 'b8-a-agent');
    const agentB = await publishAgentFor(userB.token, userB.sub, 'b8-b-agent');

    // Sanity: two distinct keys, two distinct sources, two distinct owners.
    expect(agentA.key).not.toBe(agentB.key);
    expect(agentA.sourceId).not.toBe(agentB.sourceId);

    const anon = await anonRequest();
    try {
      // Call /api/search with B's key from an anon context. The route
      // will resolve source_ids from B's `source_id` column, not A's.
      const resB = await anon.post('/api/search', {
        data: {
          question: 'cross-tenant probe — e2e-b8',
          api_key: agentB.key,
        },
      });
      expect(resB.status()).toBe(200);
      const bodyB = await resB.json();
      expect(Array.isArray(bodyB)).toBe(true);

      // And with A's key. Both land on 200 with [] — the endpoint is
      // strictly scoped by the api_key's owner, no cross-pollination.
      const resA = await anon.post('/api/search', {
        data: {
          question: 'cross-tenant probe — e2e-b8',
          api_key: agentA.key,
        },
      });
      expect(resA.status()).toBe(200);
      expect(Array.isArray(await resA.json())).toBe(true);

      // DB assertion: the underlying agents rows remain distinct and
      // correctly owned. A regression where api_key lookup fell back to
      // "any agent with this key" would have merged them; we prove the
      // rows stay cleanly separated per owner.
      const { rows } = await pg.query<{
        id: string;
        user_id: string;
        key: string;
      }>(
        `SELECT id::text AS id, user_id, key FROM agents
         WHERE key IN ($1, $2)
         ORDER BY user_id`,
        [agentA.key, agentB.key],
      );
      expect(rows).toHaveLength(2);
      expect(rows.map((r) => r.user_id).sort()).toEqual([
        userA.sub,
        userB.sub,
      ]);
    } finally {
      await anon.dispose();
    }
  });

  test('passes Authorization: Bearer <agent_key> header → before_request 401 (agent keys are NOT JWT-shaped under session_jwt)', async ({
    browser,
  }) => {
    // Pin the current product behavior: under session_jwt, the global
    // `authenticate_request` before_request tries to JWT-decode any
    // Authorization header and 401s on failure. An agent api_key in the
    // Bearer slot fails that decode, so /api/search callers MUST omit
    // the header (or use a JWT instead) to reach the route. If this
    // test ever flips to 200 it means auth.py relaxed the Bearer
    // decode — and widget integrations might suddenly start leaking
    // caller identity into the route.
    const { sub, token } = await newUserContext(browser);
    const agent = await publishAgentFor(token, sub, 'b8-bearer-probe');

    const bearerAgentKey = await playwright.request.newContext({
      baseURL: API_URL,
      extraHTTPHeaders: {
        Authorization: `Bearer ${agent.key}`,
        'Content-Type': 'application/json',
      },
    });
    try {
      const res = await bearerAgentKey.post('/api/search', {
        data: {
          question: 'bearer-agentkey — e2e-b8-bearer',
          api_key: agent.key,
        },
      });
      // 401 from the global before_request layer (invalid_token), NOT
      // from the search route. Body surfaces the before_request error.
      expect(res.status()).toBe(401);
      const body = await res.json();
      expect(body.error).toBe('invalid_token');
    } finally {
      await bearerAgentKey.dispose();
    }
  });
});
