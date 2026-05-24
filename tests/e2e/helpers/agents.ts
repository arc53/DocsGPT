/**
 * Shared agent provisioning for specs that need a published agent
 * (with a real api_key) for subsequent /stream or /search
 * calls. A PUBLISHED classic agent requires name, description, chunks,
 * retriever, prompt_id AND a source — otherwise `/api/create_agent`
 * returns 400.
 *
 * Instead of spawning /api/upload (which is Celery-ingestion-dependent
 * and orthogonal to what most specs care about), we insert a fixture
 * `sources` row directly — the schema is locked by alembic 0001_initial.
 * This mirrors the `insertFixtureSource` pattern in agents.spec.ts.
 */

import type { APIRequestContext } from '@playwright/test';
import * as playwright from '@playwright/test';

import { pg } from './db.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

/**
 * Build a multipart-capable APIRequestContext bearing `token`. Does NOT
 * set a default Content-Type (unlike `authedRequest`) so Playwright's
 * multipart boundary is the only Content-Type Flask sees.
 */
export async function multipartAuthedRequest(
  token: string,
): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Insert a minimal `sources` row owned by `userId`. Matches the DDL in
 * application/alembic/versions/0001_initial.py.
 */
export async function insertFixtureSource(
  userId: string,
  name: string,
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO sources (user_id, name, date, retriever)
     VALUES ($1, $2, now(), 'classic')
     RETURNING id::text AS id`,
    [userId, name],
  );
  const id = rows[0]?.id;
  if (!id) {
    throw new Error('insertFixtureSource: no id returned');
  }
  return id;
}

/**
 * Provision a PUBLISHED classic agent end-to-end and return {id, key}.
 *
 * Creates (1) a fresh `sources` row owned by `userId`, (2) a prompt via
 * /api/create_prompt, then (3) a published agent via /api/create_agent
 * multipart with all required fields. The returned `key` is the agent's
 * api_key — use it in /stream body as `api_key: <key>` to exercise the
 * widget/integration path.
 *
 * Callers MUST pass their own `jsonApi` (for /api/create_prompt) because
 * creating a prompt requires a JSON-Content-Type context.
 */
export async function publishClassicAgent(
  jsonApi: APIRequestContext,
  multipartApi: APIRequestContext,
  userId: string,
  name: string,
  opts: { promptName?: string; promptContent?: string } = {},
): Promise<{ id: string; key: string; sourceId: string; promptId: string }> {
  const sourceId = await insertFixtureSource(userId, `${name}-src`);

  const promptRes = await jsonApi.post('/api/create_prompt', {
    data: {
      name: opts.promptName ?? `${name}-prompt`,
      content: opts.promptContent ?? 'Be concise.',
    },
  });
  if (promptRes.status() !== 200) {
    throw new Error(
      `create_prompt failed ${promptRes.status()}: ${await promptRes.text()}`,
    );
  }
  const { id: promptId } = (await promptRes.json()) as { id: string };

  const createRes = await multipartApi.post('/api/create_agent', {
    multipart: {
      name,
      description: `e2e agent ${name}`,
      status: 'published',
      agent_type: 'classic',
      chunks: '2',
      retriever: 'classic',
      prompt_id: promptId,
      source: sourceId,
    },
  });
  if (createRes.status() !== 201) {
    throw new Error(
      `create_agent publish failed ${createRes.status()}: ${await createRes.text()}`,
    );
  }
  const body = (await createRes.json()) as { id: string; key: string };
  if (!body.id || !body.key) {
    throw new Error(`create_agent returned no id/key: ${JSON.stringify(body)}`);
  }
  return { id: body.id, key: body.key, sourceId, promptId };
}
