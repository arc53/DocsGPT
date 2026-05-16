/**
 * Tier-B · agent template gallery + adopt
 *
 * Covers B12: `GET /api/template_agents` lists rows owned by
 * `user_id = '__system__'`, and `POST /api/adopt_agent?id=…` creates a
 * user-owned copy with the same shape but a fresh `id`/`user_id`/`key`.
 *
 * The e2e DB starts with zero template rows — the bootstrap only
 * applies the schema, not template seeding. We insert a
 * `__system__`-owned row via
 * direct SQL to simulate a seeded template. This matches the brief's
 * explicit guidance ("if empty, INSERT a fake __system__ template agent
 * via SQL for the test") and avoids coupling to a future seed script
 * that doesn't exist yet.
 *
 * Contract quirks:
 *   - `/api/adopt_agent` returns HTTP 200 (not 201) on success — the
 *     response body shape is `{success: true, agent: {...}}`.
 *   - The adopted agent's status mirrors the template's — templates in
 *     the wild are typically `published`, and the new row inherits that.
 *     The route mints a fresh `key` UUID regardless.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface AgentRow {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  status: string;
  retriever: string | null;
  agent_type: string | null;
  key: string | null;
  chunks: number | null;
}

/**
 * Insert a `__system__`-owned template agent. Mirrors the shape the real
 * template seeder emits (name/description/status=published/retriever=classic).
 */
async function insertTemplateAgent(name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents (
       user_id, name, description, status, retriever, agent_type, chunks
     )
     VALUES ('__system__', $1, 'template seeded by e2e', 'published',
             'classic', 'classic', 2)
     RETURNING id::text AS id`,
    [name],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error(`insertTemplateAgent failed for ${name}`);
  return id;
}

async function fetchAgent(agentId: string): Promise<AgentRow | null> {
  const { rows } = await pg.query<AgentRow>(
    `SELECT id::text AS id, user_id, name, description, status, retriever,
            agent_type, key, chunks
       FROM agents WHERE id = CAST($1 AS uuid)`,
    [agentId],
  );
  return rows[0] ?? null;
}

test.describe('tier-b · agent templates', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('GET /api/template_agents lists __system__-owned agents only', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Baseline: fresh DB → no templates.
      const empty = await api.get('/api/template_agents');
      expect(empty.status()).toBe(200);
      expect((await empty.json()) as unknown[]).toEqual([]);

      // Seed two templates.
      const t1 = await insertTemplateAgent('template-alpha');
      const t2 = await insertTemplateAgent('template-beta');

      // Also seed a user-owned agent — must NOT appear in templates.
      const { rows: userAgentRows } = await pg.query<{ id: string }>(
        `INSERT INTO agents (user_id, name, status, retriever)
         VALUES ($1, 'user-owned', 'published', 'classic')
         RETURNING id::text AS id`,
        [sub],
      );
      const userAgentId = userAgentRows[0]?.id;
      expect(userAgentId).toBeTruthy();

      const listRes = await api.get('/api/template_agents');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as Array<{
        id: string;
        name: string;
        description: string;
        image: string;
      }>;

      const ids = new Set(list.map((t) => t.id));
      expect(ids.has(t1)).toBe(true);
      expect(ids.has(t2)).toBe(true);
      expect(ids.has(userAgentId as string)).toBe(false);

      // Order is by name.
      const names = list.map((t) => t.name);
      expect(names).toEqual([...names].sort());
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('POST /api/adopt_agent creates a user-owned copy with a fresh id and key', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const templateId = await insertTemplateAgent('adopt-me');

      const res = await api.post(`/api/adopt_agent?id=${templateId}`);
      expect(
        res.status(),
        `adopt_agent expected 200, got ${res.status()} ${await res.text()}`,
      ).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        agent: {
          id: string;
          name: string;
          description: string;
          status: string;
          key: string;
          retriever: string;
        };
      };
      expect(body.success).toBe(true);
      const adopted = body.agent;

      // Fresh id, not the template's.
      expect(adopted.id).not.toBe(templateId);
      expect(adopted.id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );
      // Fresh key.
      expect(adopted.key).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );

      // Name/description copied.
      expect(adopted.name).toBe('adopt-me');
      expect(adopted.description).toBe('template seeded by e2e');

      // DB: copy is owned by the user, not __system__.
      const row = await fetchAgent(adopted.id);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(sub);
      expect(row!.retriever).toBe('classic');

      // Template row is untouched.
      const templateRow = await fetchAgent(templateId);
      expect(templateRow!.user_id).toBe('__system__');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('adopted agent is usable via /api/get_agent and appears in the user list', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const templateId = await insertTemplateAgent('adopt-usable');

      const adoptRes = await api.post(`/api/adopt_agent?id=${templateId}`);
      expect(adoptRes.status()).toBe(200);
      const { agent } = (await adoptRes.json()) as { agent: { id: string } };

      // /api/get_agent resolves the new row for this user (cross-tenant
      // 404 is proven by agents.spec.ts; here we just need a positive hit).
      const getRes = await api.get(`/api/get_agent?id=${agent.id}`);
      expect(getRes.status()).toBe(200);
      const getBody = (await getRes.json()) as { id: string; name: string };
      expect(getBody.id).toBe(agent.id);
      expect(getBody.name).toBe('adopt-usable');

      // /api/get_agents shows it in the user's own list. The list filter in
      // routes.py hides agents with no source / no retriever / non-workflow
      // type — our template has retriever='classic', so it survives.
      const listRes = await api.get('/api/get_agents');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as Array<{ id: string }>;
      expect(list.some((a) => a.id === agent.id)).toBe(true);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('adopt unknown template id returns 404', async ({ browser }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Random UUID, no matching template row.
      const res = await api.post(
        '/api/adopt_agent?id=00000000-0000-0000-0000-000000000000',
      );
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
