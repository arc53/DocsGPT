/**
 * Tier-B · agent incoming webhook
 *
 * Covers B11: minting of `agents.incoming_webhook_token` via
 * `GET /api/agent_webhook?id=…`, POSTing the resolved URL triggers a
 * Celery task via `process_agent_webhook.delay(...)`, token is
 * case-insensitive thanks to the CITEXT UNIQUE column, and an unknown
 * token 404s via the `require_agent` decorator (application/api/user/base.py:203).
 *
 * Design note: we do NOT wait on the Celery task to finish — it requires
 * a real agent executor and the mock LLM, which is orthogonal to what
 * this spec protects. The contract under test is:
 *   1) agent_webhook mints and persists a CITEXT token exactly once,
 *   2) the listener resolves the token (including case-variants) and
 *      `process_agent_webhook.delay` enqueues a task id,
 *   3) invalid tokens 404.
 *
 * Agent rows are inserted directly (mirrors `agent-pin.spec.ts`) so we
 * don't need to feed /api/create_agent a real source to publish.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface AgentWebhookRow {
  id: string;
  incoming_webhook_token: string | null;
}

async function createAgent(ownerSub: string, name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents (user_id, name, status, retriever)
     VALUES ($1, $2, 'published', 'classic')
     RETURNING id::text AS id`,
    [ownerSub, name],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error(`createAgent failed for ${name}`);
  return id;
}

async function fetchAgent(agentId: string): Promise<AgentWebhookRow | null> {
  const { rows } = await pg.query<AgentWebhookRow>(
    `SELECT id::text AS id, incoming_webhook_token
       FROM agents WHERE id = CAST($1 AS uuid)`,
    [agentId],
  );
  return rows[0] ?? null;
}

/** Pull the path component after `/api/webhooks/agents/`. */
function extractToken(webhookUrl: string): string {
  const parts = webhookUrl.split('/api/webhooks/agents/');
  if (parts.length !== 2 || !parts[1]) {
    throw new Error(`unexpected webhook URL shape: ${webhookUrl}`);
  }
  return parts[1];
}

test.describe('tier-b · agent webhook', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('mint: first GET /api/agent_webhook creates the token; subsequent calls return the same one', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createAgent(sub, 'webhook-mint');
      // Pre-state: token column is NULL.
      expect((await fetchAgent(agentId))!.incoming_webhook_token).toBeNull();

      const first = await api.get(`/api/agent_webhook?id=${agentId}`);
      expect(
        first.status(),
        `first GET expected 200, got ${first.status()} ${await first.text()}`,
      ).toBe(200);
      const firstBody = (await first.json()) as { success: boolean; webhook_url: string };
      expect(firstBody.success).toBe(true);
      expect(firstBody.webhook_url).toContain('/api/webhooks/agents/');
      const token1 = extractToken(firstBody.webhook_url);

      // DB: the token has landed on the agent row.
      const rowAfterMint = await fetchAgent(agentId);
      expect(rowAfterMint!.incoming_webhook_token).toBe(token1);

      // Second call must NOT rotate — returns the same token.
      const second = await api.get(`/api/agent_webhook?id=${agentId}`);
      expect(second.status()).toBe(200);
      const secondBody = (await second.json()) as { webhook_url: string };
      const token2 = extractToken(secondBody.webhook_url);
      expect(token2).toBe(token1);

      // And the DB still holds that one token.
      expect((await fetchAgent(agentId))!.incoming_webhook_token).toBe(token1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('dispatch: POST /api/webhooks/agents/<token> enqueues a Celery task and returns task_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createAgent(sub, 'webhook-dispatch');
      const mintRes = await api.get(`/api/agent_webhook?id=${agentId}`);
      expect(mintRes.status()).toBe(200);
      const webhookToken = extractToken(
        ((await mintRes.json()) as { webhook_url: string }).webhook_url,
      );

      // Fire the inbound webhook. No Bearer header — the listener is
      // authenticated via the URL token only (see `require_agent` decorator).
      const fireCtx = await playwright.request.newContext({
        baseURL: process.env.API_URL ?? 'http://127.0.0.1:7099',
        extraHTTPHeaders: { 'Content-Type': 'application/json' },
      });
      try {
        const fire = await fireCtx.post(
          `/api/webhooks/agents/${webhookToken}`,
          { data: { event: 'ping', payload: { n: 1 } } },
        );
        expect(
          fire.status(),
          `POST webhook expected 200, got ${fire.status()} ${await fire.text()}`,
        ).toBe(200);
        const body = (await fire.json()) as { success: boolean; task_id: string };
        expect(body.success).toBe(true);
        // task_id is the Celery task UUID — shape check only, the worker's
        // outcome is out of scope for this spec.
        expect(body.task_id).toMatch(
          /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
        );
      } finally {
        await fireCtx.dispose();
      }
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('citext: lowercase variant of the minted token still resolves', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createAgent(sub, 'webhook-citext');
      const mintRes = await api.get(`/api/agent_webhook?id=${agentId}`);
      const webhookToken = extractToken(
        ((await mintRes.json()) as { webhook_url: string }).webhook_url,
      );

      // `secrets.token_urlsafe(32)` is base64url — has mixed case unless it
      // happens to emit all-lowercase/digits. Skip if lowercasing is a no-op
      // (vacuous case-insensitivity).
      const lowerToken = webhookToken.toLowerCase();
      test.skip(
        lowerToken === webhookToken,
        'minted token has no upper-case chars; citext check is vacuous',
      );

      const fireCtx = await playwright.request.newContext({
        baseURL: process.env.API_URL ?? 'http://127.0.0.1:7099',
        extraHTTPHeaders: { 'Content-Type': 'application/json' },
      });
      try {
        const fire = await fireCtx.post(
          `/api/webhooks/agents/${lowerToken}`,
          { data: {} },
        );
        expect(
          fire.status(),
          `lowercase token expected 200, got ${fire.status()} ${await fire.text()}`,
        ).toBe(200);
        const body = (await fire.json()) as { success: boolean; task_id: string };
        expect(body.success).toBe(true);
      } finally {
        await fireCtx.dispose();
      }
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('invalid token: POST /api/webhooks/agents/<garbage> returns 404', async () => {
    const fireCtx = await playwright.request.newContext({
      baseURL: process.env.API_URL ?? 'http://127.0.0.1:7099',
      extraHTTPHeaders: { 'Content-Type': 'application/json' },
    });
    try {
      const res = await fireCtx.post(
        '/api/webhooks/agents/definitely-not-a-real-token-xyz',
        { data: {} },
      );
      expect(res.status()).toBe(404);
      const body = (await res.json()) as { success: boolean; message?: string };
      expect(body.success).toBe(false);
    } finally {
      await fireCtx.dispose();
    }
  });
});
