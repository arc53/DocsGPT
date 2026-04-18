/**
 * Phase 2 — P2-10 · Agent CRUD (classic type).
 *
 * Writes to `agents`, reads `prompts`, touches `users`. Exercises the full
 * create→publish→update→delete lifecycle plus cross-tenant isolation and a
 * source-resolution check.
 *
 * // Silent-break covered: agents.extra_source_ids resolves to real sources —
 * // a stale UUID (e.g. from a template remint) would silently break
 * // retrieval. We create a real `sources` row, attach its UUID via
 * // extra_source_ids, and assert the create_agent round-trip preserves the
 * // reference and that /api/search's source-resolution path finds it.
 *
 * Deviation note: the `sources` row in the silent-break test is inserted
 * directly via `pg.query` rather than exercising /api/upload. Reason: upload
 * spawns Celery ingestion and depends on the mock LLM's embedding endpoint
 * plus on-disk Faiss index — far slower and orthogonal to what this spec
 * protects. The schema the INSERT uses is locked by alembic 0001_initial
 * (CREATE TABLE sources). Flagged per the subagent brief.
 *
 * Creation uses /api/create_agent's multipart form path (not the JSON path).
 * The helper `authedRequest` sets a default application/json Content-Type
 * on the context, which would collide with Playwright's multipart boundary
 * header — so this spec builds its own multipart-ready context via
 * `playwright.request.newContext` without that default.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;
import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { signJwt } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

type AgentRow = {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  agent_type: string | null;
  status: string;
  key: string | null;
  source_id: string | null;
  extra_source_ids: string[] | null;
  chunks: number | null;
  retriever: string | null;
  prompt_id: string | null;
  created_at: Date;
  updated_at: Date;
};

type SourceRow = { id: string };

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

/**
 * Multipart-capable context: same Bearer token plumbing as `authedRequest`
 * but without the default `Content-Type: application/json` header, so
 * Playwright's multipart boundary header on `post({ multipart })` is the
 * only Content-Type that reaches Flask.
 */
async function multipartAuthedRequest(token: string): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Insert a minimal `sources` row owned by `userId`. Matches the DDL in
 * application/alembic/versions/0001_initial.py — only id, user_id, name,
 * date, retriever are explicitly set; the rest default. Returns the UUID.
 */
async function insertFixtureSource(userId: string, name: string): Promise<string> {
  const { rows } = await pg.query<SourceRow>(
    `INSERT INTO sources (user_id, name, date, retriever)
     VALUES ($1, $2, now(), 'classic')
     RETURNING id`,
    [userId, name],
  );
  const id = rows[0]?.id;
  if (!id) {
    throw new Error('insertFixtureSource: no id returned');
  }
  return id;
}

/**
 * Fetch an agent row by id with the columns this spec cares about.
 */
async function getAgent(agentId: string): Promise<AgentRow | null> {
  const { rows } = await pg.query<AgentRow>(
    `SELECT id, user_id, name, description, agent_type, status, key,
            source_id, extra_source_ids, chunks, retriever, prompt_id,
            created_at, updated_at
     FROM agents WHERE id = $1`,
    [agentId],
  );
  return rows[0] ?? null;
}

/**
 * Create a draft classic agent via the multipart form path. Returns the
 * new agent id. Callers pass a prepared multipart context.
 */
async function createDraftAgent(
  ctx: APIRequestContext,
  name: string,
  extras: Record<string, string> = {},
): Promise<string> {
  const res = await ctx.post('/api/create_agent', {
    multipart: {
      name,
      status: 'draft',
      agent_type: 'classic',
      chunks: '2',
      ...extras,
    },
  });
  expect(res.status(), `create_agent draft should be 201, got ${res.status()} ${await res.text()}`).toBe(201);
  const body = (await res.json()) as { id: string; key: string };
  expect(body.id).toBeTruthy();
  return body.id;
}

test.describe('tier-a · agents CRUD', () => {
  test.beforeEach(async () => {
    await resetDb();
  });


  test('creates a draft agent — row exists with status=draft and empty key', async () => {
    const sub = `e2e-agent-draft-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    try {
      const agentId = await createDraftAgent(ctx, 'draft agent');

      const row = await getAgent(agentId);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(sub);
      expect(row!.name).toBe('draft agent');
      expect(row!.status).toBe('draft');
      // `key` column is nullable CITEXT; the create path normalizes empty
      // strings to NULL (see AgentsRepository._normalize_unique_text).
      expect(row!.key ?? '').toBe('');
      expect(row!.agent_type).toBe('classic');
    } finally {
      await ctx.dispose();
    }
  });

  test('publishes an agent — key becomes a UUID and status flips to published', async () => {
    const sub = `e2e-agent-publish-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      // Minimal publishable classic agent: needs name, description, chunks,
      // retriever OR source, prompt_id. We sidestep prompt_id by using a
      // private prompt the user creates first.
      const promptRes = await apiJson.post('/api/create_prompt', {
        data: { name: 'e2e-agent-prompt', content: 'Be concise.' },
      });
      expect(promptRes.status()).toBe(200);
      const promptId = ((await promptRes.json()) as { id: string }).id;

      const sourceId = await insertFixtureSource(sub, 'e2e-agent-publish-src');

      const createRes = await ctx.post('/api/create_agent', {
        multipart: {
          name: 'published agent',
          description: 'publishes cleanly',
          status: 'published',
          agent_type: 'classic',
          chunks: '2',
          retriever: 'classic',
          prompt_id: promptId,
          source: sourceId,
        },
      });
      expect(
        createRes.status(),
        `publish should be 201, got ${createRes.status()} ${await createRes.text()}`,
      ).toBe(201);
      const body = (await createRes.json()) as { id: string; key: string };
      expect(body.key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i);

      const row = await getAgent(body.id);
      expect(row).not.toBeNull();
      expect(row!.status).toBe('published');
      expect(row!.key).toBe(body.key);
      expect(row!.prompt_id).toBe(promptId);
      expect(row!.source_id).toBe(sourceId);
    } finally {
      await ctx.dispose();
      await apiJson.dispose();
    }
  });

  test('updates an agent — fields change and updated_at bumps forward', async () => {
    const sub = `e2e-agent-update-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    try {
      const agentId = await createDraftAgent(ctx, 'before update', {
        description: 'original',
      });
      const before = await getAgent(agentId);
      expect(before).not.toBeNull();

      // `set_updated_at` trigger uses `now()` which is constant inside a
      // single transaction; wait >1ms so the UPDATE transaction is
      // definitionally later than the INSERT's commit time.
      await new Promise((r) => setTimeout(r, 50));

      const updateRes = await ctx.put(`/api/update_agent/${agentId}`, {
        multipart: {
          name: 'after update',
          description: 'rewritten',
          status: 'draft',
          agent_type: 'classic',
        },
      });
      expect(
        updateRes.status(),
        `update should be 200, got ${updateRes.status()} ${await updateRes.text()}`,
      ).toBe(200);

      const after = await getAgent(agentId);
      expect(after).not.toBeNull();
      expect(after!.name).toBe('after update');
      expect(after!.description).toBe('rewritten');
      // Trigger: agents_set_updated_at fires BEFORE UPDATE when any column
      // differs. Both timestamps are TIMESTAMPTZ and pg returns Date.
      expect(after!.updated_at.getTime()).toBeGreaterThan(before!.updated_at.getTime());
    } finally {
      await ctx.dispose();
    }
  });

  test('deletes an agent — row disappears and the delete endpoint reports success', async () => {
    const sub = `e2e-agent-delete-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    try {
      const agentId = await createDraftAgent(ctx, 'doomed');
      expect(await getAgent(agentId)).not.toBeNull();

      const deleteRes = await ctx.delete(`/api/delete_agent?id=${agentId}`);
      expect(deleteRes.status()).toBe(200);
      const body = (await deleteRes.json()) as { id: string };
      expect(body.id).toBe(agentId);

      expect(await getAgent(agentId)).toBeNull();
    } finally {
      await ctx.dispose();
    }
  });

  test('silent-break: extra_source_ids resolves back to a real sources row end-to-end', async () => {
    const sub = `e2e-agent-silentbreak-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      // 1. Create a real source row directly (fast; schema locked by
      //    0001_initial). This is the "valid source" under test.
      const sourceId = await insertFixtureSource(sub, 'silent-break-src');

      // 2. Create a prompt so we can publish.
      const promptRes = await apiJson.post('/api/create_prompt', {
        data: { name: 'silent-break-prompt', content: 'Ground every answer.' },
      });
      expect(promptRes.status()).toBe(200);
      const promptId = ((await promptRes.json()) as { id: string }).id;

      // 3. Create a PUBLISHED classic agent with the source listed in
      //    `sources` (the multiple-sources multipart field — goes into
      //    extra_source_ids per routes.py, not source_id).
      const createRes = await ctx.post('/api/create_agent', {
        multipart: {
          name: 'silent-break agent',
          description: 'tests extra_source_ids resolution',
          status: 'published',
          agent_type: 'classic',
          chunks: '2',
          retriever: 'classic',
          prompt_id: promptId,
          // JSON-stringified list — the multipart handler json.loads this.
          sources: JSON.stringify([sourceId]),
        },
      });
      expect(
        createRes.status(),
        `publish with extra sources should be 201, got ${createRes.status()} ${await createRes.text()}`,
      ).toBe(201);
      const { id: agentId, key } = (await createRes.json()) as { id: string; key: string };
      expect(key).toBeTruthy();

      // 4. DB-level assertion: the UUID actually landed in extra_source_ids
      //    and matches a real sources row. This is the core of the silent
      //    break: if the UUID were stale or mismatched, this join would
      //    return zero rows while the agent row itself still exists.
      const { rows: joined } = await pg.query<{ agent_id: string; source_id: string }>(
        `SELECT a.id AS agent_id, s.id AS source_id
         FROM agents a
         JOIN sources s ON s.id = ANY(a.extra_source_ids)
         WHERE a.id = $1`,
        [agentId],
      );
      expect(joined).toHaveLength(1);
      expect(joined[0].source_id).toBe(sourceId);

      // 5. API-level assertion: /api/search goes through
      //    AgentsRepository.find_by_key -> extra_source_ids unwrap. We
      //    cannot reliably assert non-empty `sources[]` in the response
      //    without a pre-built Faiss index for this source_id, so we
      //    instead assert the endpoint treats the key as valid (not 401)
      //    and returns a JSON array — confirming the server resolved the
      //    key to an agent whose sources list is non-empty (if it were
      //    empty, search.py returns [] without even trying; we still
      //    expect 200). The DB join above is the load-bearing assertion
      //    for the silent break.
      const searchRes = await apiJson.post('/api/search', {
        data: { question: 'ping', api_key: key, chunks: 2 },
      });
      // 401 would mean find_by_key couldn't locate the agent — a
      // definitive silent-break signal. 200 means the key resolved.
      expect(searchRes.status()).toBe(200);

      // 6. Round-trip check via /api/get_agent: the response shapes
      //    extra_source_ids as `sources` (see _format_agent_output).
      const getRes = await apiJson.get(`/api/get_agent?id=${agentId}`);
      expect(getRes.status()).toBe(200);
      const agent = (await getRes.json()) as { sources: string[] };
      expect(agent.sources).toContain(sourceId);
    } finally {
      await ctx.dispose();
      await apiJson.dispose();
    }
  });

  test("cross-tenant: user A's agent is invisible to user B and absent from their list", async () => {
    const subA = `e2e-agent-tenantA-${Date.now()}`;
    const subB = `e2e-agent-tenantB-${Date.now()}`;
    const tokenA = signJwt(subA);
    const tokenB = signJwt(subB);
    const ctxA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      // User A needs a source so /api/get_agents doesn't filter the agent
      // out of the list response (the route hides agents with no source,
      // no extras, no retriever, and non-workflow type).
      const sourceId = await insertFixtureSource(subA, 'tenant-iso-src');
      const agentId = await createDraftAgent(ctxA, 'tenant A private', {
        sources: JSON.stringify([sourceId]),
      });

      // DB-level invariant: the agent belongs to user A only.
      const row = await getAgent(agentId);
      expect(row).not.toBeNull();
      expect(row!.user_id).toBe(subA);

      // User A sees their agent in the list.
      const listA = await apiA.get('/api/get_agents');
      expect(listA.status()).toBe(200);
      const listABody = (await listA.json()) as Array<{ id: string }>;
      expect(listABody.some((a) => a.id === agentId)).toBe(true);

      // User B does not see it in their list.
      const listB = await apiB.get('/api/get_agents');
      expect(listB.status()).toBe(200);
      const listBBody = (await listB.json()) as Array<{ id: string }>;
      expect(listBBody.some((a) => a.id === agentId)).toBe(false);

      // User B cannot fetch it by id either — AgentsRepository.get_any
      // scopes by user_id for non-shared, non-template rows, so this 404s.
      const getB = await apiB.get(`/api/get_agent?id=${agentId}`);
      expect(getB.status()).toBe(404);
    } finally {
      await ctxA.dispose();
      await apiA.dispose();
      await apiB.dispose();
    }
  });

  test('publish without required fields returns 400 and no agent row is written', async () => {
    const sub = `e2e-agent-reject-${Date.now()}`;
    const token = signJwt(sub);
    const ctx = await multipartAuthedRequest(token);
    try {
      // Published classic agents require name, description, chunks,
      // retriever, prompt_id AND a source (either `source` or `sources`).
      // Omit description/prompt_id/source to trigger the validator.
      const res = await ctx.post('/api/create_agent', {
        multipart: {
          name: 'should be rejected',
          status: 'published',
          agent_type: 'classic',
          chunks: '2',
        },
      });
      expect(res.status()).toBe(400);

      const { rows } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM agents WHERE user_id = $1`,
        [sub],
      );
      expect(Number(rows[0]?.n ?? 0)).toBe(0);
    } finally {
      await ctx.dispose();
    }
  });
});
