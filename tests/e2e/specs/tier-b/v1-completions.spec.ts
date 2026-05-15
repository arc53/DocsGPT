// Tier-B · /v1/chat/completions + /v1/models (OpenAI-compatible)
/**
 * B9 · OpenAI-compatible endpoints.
 *
 * `application/api/v1/routes.py` exposes `/v1/chat/completions` (POST)
 * and `/v1/models` (GET). Both read an agent API key from
 * `Authorization: Bearer <agent.key>` via `_extract_bearer_token()`
 * and look up the owning agent via `AgentsRepository.find_by_key`.
 *
 * Contract gotcha — interaction with the global JWT middleware
 * ------------------------------------------------------------
 * Under `AUTH_TYPE=session_jwt` (the e2e default) the Flask
 * `before_request` in `application/app.py` runs `handle_auth()`
 * BEFORE the blueprint is reached. `handle_auth()` tries to JWT-
 * decode any present `Authorization: Bearer <value>` and 401s on
 * decode failure. Agent API keys are UUIDs (not JWTs), so passing
 * one in the Bearer slot gets rejected at the before_request layer
 * before the v1 route can run.
 *
 * Consequence for this spec:
 *   - missing header → 401 at the v1 route (reachable).
 *   - invalid key that happens to be JWT-shaped (e.g. a JWT signed
 *     for a non-existent sub) → 401 at v1 route (Invalid API key).
 *   - real agent api_key → currently 401 at the before_request
 *     layer under session_jwt. Covered by a `test.fixme` to pin
 *     the product-level expectation.
 *
 * If the before_request gate ever learns to skip `/v1/*` paths
 * (or to fall back to "treat bearer as opaque token for /v1/*"),
 * the fixme'd tests unfixme and start enforcing the happy-path
 * contract.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import {
  multipartAuthedRequest,
  publishClassicAgent,
} from '../../helpers/agents.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

/**
 * Context with NO Authorization header — lets the global before_request
 * fall through (handle_auth returns None), so the v1 route runs and
 * can emit its own 401 body.
 */
async function anonRequest(): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: { 'Content-Type': 'application/json' },
  });
}

/**
 * Context with an arbitrary Bearer value. The value is signed as a JWT
 * so it passes the global `handle_auth()` decode and the v1 route is
 * reached; the route then tries to look up an agent with that exact
 * key and 401s ("Invalid API key") since no such agent exists.
 */
async function jwtBearerRequest(bearer: string): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${bearer}`,
      'Content-Type': 'application/json',
    },
  });
}

/**
 * Helper to publish a fresh classic agent for a user. Returns the
 * {id, key}.
 */
async function publishAgentFor(
  token: string,
  userId: string,
  name: string,
): Promise<{ id: string; key: string }> {
  const jsonApi = await authedRequest(playwright, token);
  const multipart = await multipartAuthedRequest(token);
  try {
    const result = await publishClassicAgent(jsonApi, multipart, userId, name);
    return { id: result.id, key: result.key };
  } finally {
    await multipart.dispose();
    await jsonApi.dispose();
  }
}

test.describe('tier-b · /v1 OpenAI-compatible endpoints', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('POST /v1/chat/completions without Authorization → 401 with v1 error envelope', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    void sub;
    void token;

    const anon = await anonRequest();
    try {
      const res = await anon.post('/v1/chat/completions', {
        data: {
          model: 'docsgpt',
          messages: [{ role: 'user', content: 'hi — e2e-b9-no-auth' }],
          stream: false,
        },
      });
      expect(res.status()).toBe(401);
      const body = await res.json();
      // v1 envelope: { error: { message, type: "auth_error" } }.
      expect(body.error?.type).toBe('auth_error');
      expect(body.error?.message).toMatch(/Missing Authorization/i);
    } finally {
      await anon.dispose();
    }
  });

  test('POST /v1/chat/completions with a JWT-shaped but non-matching Bearer → 401 Invalid API key (route-level)', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    void sub;
    void token;

    // Sign a JWT that decodes cleanly under JWT_SECRET_KEY but isn't
    // an agent api_key. The global before_request passes it through;
    // the route then calls find_by_key(<jwt>) → no match → 401.
    const bogusJwt = signJwt('nobody-really');
    const api = await jwtBearerRequest(bogusJwt);
    try {
      // /v1/models uses the same Bearer→api_key lookup, so it's the
      // cleanest path to exercise the invalid-key branch without the
      // body validation on /chat/completions getting in the way.
      const res = await api.get('/v1/models');
      expect(res.status()).toBe(401);
      const body = await res.json();
      expect(body.error?.type).toBe('auth_error');
      expect(body.error?.message).toMatch(/Invalid API key/i);
    } finally {
      await api.dispose();
    }
  });

  test('POST /v1/chat/completions with Authorization header but missing body → 400 invalid_request', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    void sub;
    void token;

    // JWT-shaped bearer passes before_request. Route then fails on the
    // `data or data.get("messages")` guard BEFORE looking up the key,
    // so we don't need a real agent.
    const bogusJwt = signJwt('b9-body-shape-check');
    const api = await jwtBearerRequest(bogusJwt);
    try {
      const res = await api.post('/v1/chat/completions', {
        data: { model: 'docsgpt', stream: false },
      });
      expect(res.status()).toBe(400);
      const body = await res.json();
      expect(body.error?.type).toBe('invalid_request');
      expect(body.error?.message).toMatch(/messages/i);
    } finally {
      await api.dispose();
    }
  });

  test('GET /v1/models without Authorization → 401 with v1 error envelope', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    void sub;
    void token;

    const anon = await anonRequest();
    try {
      const res = await anon.get('/v1/models');
      expect(res.status()).toBe(401);
      const body = await res.json();
      expect(body.error?.type).toBe('auth_error');
      expect(body.error?.message).toMatch(/Missing Authorization/i);
    } finally {
      await anon.dispose();
    }
  });

  test('agent api_key lookup path exists: publishing an agent persists a `key` column that matches what the v1 route would query', async ({
    browser,
  }) => {
    // This test proves the DB-side half of the v1 contract — the
    // `agents.key` column is populated on publish and is unique per
    // agent. The v1 route calls `AgentsRepository.find_by_key(key)`
    // against this column; a regression where the key isn't persisted
    // (e.g. null key after create_agent) would surface as Invalid API
    // key on EVERY v1 call, not just malformed ones.
    const { sub, token } = await newUserContext(browser);
    const agent = await publishAgentFor(token, sub, 'b9-key-persist');

    expect(agent.key).toBeTruthy();
    expect(agent.key).toMatch(/^[0-9a-f-]{20,}$/i);

    // Directly verify the agents row has the key and is owned by our sub.
    const { rows } = await pg.query<{
      id: string;
      user_id: string;
      key: string;
      status: string;
    }>(
      `SELECT id::text AS id, user_id, key, status
         FROM agents WHERE id = CAST($1 AS uuid)`,
      [agent.id],
    );
    expect(rows).toHaveLength(1);
    expect(rows[0].user_id).toBe(sub);
    expect(rows[0].key).toBe(agent.key);
    expect(rows[0].status).toBe('published');
  });

  test(
    'POST /v1/chat/completions with agent api_key Bearer → 200 OpenAI envelope',
    async ({ browser }) => {
      const { sub, token } = await newUserContext(browser);
      const agent = await publishAgentFor(token, sub, 'b9-happy-path');

      const api = await jwtBearerRequest(agent.key);
      try {
        const res = await api.post('/v1/chat/completions', {
          data: {
            model: 'docsgpt',
            messages: [{ role: 'user', content: 'hello — e2e-b9-happy' }],
            stream: false,
          },
        });
        expect(res.status()).toBe(200);
        const body = await res.json();
        expect(body.object).toBe('chat.completion');
        expect(body.choices).toHaveLength(1);
        expect(body.choices[0].message.role).toBe('assistant');
      } finally {
        await api.dispose();
      }
    },
  );

  test(
    'POST /v1/chat/completions with stream:true emits SSE chunks terminated by data: [DONE]',
    async ({ browser }) => {
      const { sub, token } = await newUserContext(browser);
      const agent = await publishAgentFor(token, sub, 'b9-stream-happy');

      const api = await jwtBearerRequest(agent.key);
      try {
        const res = await api.post('/v1/chat/completions', {
          data: {
            model: 'docsgpt',
            messages: [{ role: 'user', content: 'hi — e2e-b9-stream' }],
            stream: true,
          },
        });
        expect(res.status()).toBe(200);
        const text = await res.text();
        expect(text.trim().endsWith('data: [DONE]')).toBe(true);
      } finally {
        await api.dispose();
      }
    },
  );

  test(
    'GET /v1/models with agent api_key Bearer → 200 with model list keyed on agents rows',
    async ({ browser }) => {
      const { sub, token } = await newUserContext(browser);
      const agent = await publishAgentFor(token, sub, 'b9-models-happy');

      const api = await jwtBearerRequest(agent.key);
      try {
        const res = await api.get('/v1/models');
        expect(res.status()).toBe(200);
        const body = await res.json();
        expect(body.object).toBe('list');
        expect(Array.isArray(body.data)).toBe(true);
        const ids = body.data.map((m: { id: string }) => m.id);
        expect(ids).toContain(agent.id);
      } finally {
        await api.dispose();
      }
    },
  );
});
