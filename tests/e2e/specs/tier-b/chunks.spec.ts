/**
 * Phase 3 Tier-B · chunks (B3) — get / add / update / delete chunks.
 *
 * Exercises `application/api/user/sources/chunks.py`. All chunk endpoints go
 * through `get_vector_store(str(doc["id"]))` (application/api/user/base.py:
 * 150-165) — so the caller-supplied source id MUST match the faiss
 * directory name on disk. This is not how the normal upload flow leaves
 * things (see `helpers/uploads.ts` module header for the DB-id ↔
 * faiss-dir-id mismatch), so the setup here is deliberately surgical:
 *
 *   1. POST /api/upload a small PDF as a single "cold" user.
 *   2. After SUCCESS, scan `indexes/` for the newest `index.faiss` —
 *      that's the worker-minted UUID.
 *   3. Wipe the DB row the upload produced and INSERT a fresh sources
 *      row whose `id` = the faiss dir UUID. Now chunks endpoints resolve.
 *
 * This is expensive (~3-5s first run because docling loads PDF pipeline
 * lazily), so the setup runs once per worker in `beforeAll`. Each test
 * operates on the same seeded source but only mutates/rolls-back
 * chunk-scoped state — no cross-test pollution because `get_chunks`
 * returns the current state of the vectorstore, and deletions in test N
 * don't affect test N+1's assertions as long as each test adds its own
 * probe chunk first.
 */

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext, Browser } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import {
  findNewestIndexDir,
  multipartContext,
  postUpload,
  seedSourceWithId,
  waitForTask,
} from '../../helpers/uploads.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SMALL_PDF = resolve(HERE, '..', '..', 'fixtures', 'docs', 'small.pdf');

interface GetChunksResponse {
  page: number;
  per_page: number;
  total: number;
  chunks: Array<{
    doc_id: string;
    text: string;
    metadata: Record<string, unknown>;
  }>;
}

let sharedUser: { sub: string; token: string } | null = null;
let sharedSourceId: string | null = null;

/**
 * Shared test-surface setup: upload small.pdf, reconcile the DB row with
 * the faiss directory UUID, return the {token, sourceId} pair subsequent
 * tests use. Runs once per worker — Playwright's `beforeAll` guarantees.
 */
async function provisionChunksSource(browser: Browser): Promise<{
  sub: string;
  token: string;
  sourceId: string;
}> {
  await resetDb();
  const { context, sub, token } = await newUserContext(browser);
  await context.close(); // we just need the token; no page traffic in setup
  const multi = await multipartContext(token);
  const apiJson = await authedRequest(playwright, token);
  try {
    const startedAt = Date.now() - 2000; // small skew buffer for mtime compare
    const taskId = await postUpload(multi, SMALL_PDF, {
      user: sub,
      name: `chunks-fixture-${Date.now()}`,
    });
    const final = await waitForTask(apiJson, taskId, 60_000);
    if (final.status !== 'SUCCESS') {
      throw new Error(
        `chunks fixture upload did not succeed: ${JSON.stringify(final)}`,
      );
    }

    // Find the freshly-written faiss directory — that UUID is the one the
    // chunks endpoints will resolve the vectorstore from.
    const faissDirId = await findNewestIndexDir(startedAt);
    if (!faissDirId) {
      throw new Error('chunks fixture: no index.faiss materialised on disk');
    }

    // Purge the PG row the upload_index path produced (its id doesn't match
    // the faiss dir) and replace it with one pinned to the faiss UUID.
    await pg.query(`DELETE FROM sources WHERE user_id = $1`, [sub]);
    await seedSourceWithId(faissDirId, sub, {
      name: 'chunks-fixture',
      type: 'local',
    });
    return { sub, token, sourceId: faissDirId };
  } finally {
    await multi.dispose();
    await apiJson.dispose();
  }
}

async function fetchChunks(
  api: APIRequestContext,
  sourceId: string,
  opts: { page?: number; perPage?: number; search?: string } = {},
): Promise<GetChunksResponse> {
  const params = new URLSearchParams();
  params.set('id', sourceId);
  params.set('page', String(opts.page ?? 1));
  params.set('per_page', String(opts.perPage ?? 50));
  if (opts.search) params.set('search', opts.search);
  const res = await api.get(`/api/get_chunks?${params.toString()}`);
  if (res.status() !== 200) {
    throw new Error(
      `GET /api/get_chunks failed ${res.status()}: ${await res.text()}`,
    );
  }
  return (await res.json()) as GetChunksResponse;
}

test.describe('tier-b · chunks CRUD', () => {
  test.beforeAll(async ({ browser }) => {
    const provisioned = await provisionChunksSource(browser);
    sharedUser = { sub: provisioned.sub, token: provisioned.token };
    sharedSourceId = provisioned.sourceId;
  });

  test('GET /api/get_chunks returns chunks for the ingested PDF', async () => {
    if (!sharedUser || !sharedSourceId) throw new Error('setup missing');
    const api = await authedRequest(playwright, sharedUser.token);
    try {
      const body = await fetchChunks(api, sharedSourceId, { perPage: 50 });
      // small.pdf fixture contains ~1 paragraph → >= 1 chunk after chunking.
      expect(body.total).toBeGreaterThanOrEqual(1);
      expect(body.chunks.length).toBeGreaterThanOrEqual(1);
      expect(body.chunks[0]).toHaveProperty('doc_id');
      expect(body.chunks[0]).toHaveProperty('text');
      expect(body.chunks[0].metadata).toBeDefined();
    } finally {
      await api.dispose();
    }
  });

  test('POST /api/add_chunk inserts a new chunk; get_chunks total reflects it', async () => {
    if (!sharedUser || !sharedSourceId) throw new Error('setup missing');
    const api = await authedRequest(playwright, sharedUser.token);
    try {
      const before = await fetchChunks(api, sharedSourceId);
      const beforeCount = before.total;

      const probeText = `e2e-chunks-add-${Date.now()}`;
      const addRes = await api.post('/api/add_chunk', {
        data: { id: sharedSourceId, text: probeText },
      });
      expect(addRes.status()).toBe(201);
      const addBody = (await addRes.json()) as {
        message: string;
        chunk_id: string | string[];
      };
      expect(addBody.message).toMatch(/added/i);
      // FAISS.add_documents returns a list of doc_ids — chunks.py passes it
      // through verbatim (sources/chunks.py:154).
      expect(addBody.chunk_id).toBeTruthy();

      const after = await fetchChunks(api, sharedSourceId);
      expect(after.total).toBe(beforeCount + 1);
      const found = after.chunks.find((c) => c.text === probeText);
      expect(found, 'new chunk text not visible in get_chunks').toBeDefined();
    } finally {
      await api.dispose();
    }
  });

  test('PUT /api/update_chunk replaces text; old chunk gone, new chunk present', async () => {
    if (!sharedUser || !sharedSourceId) throw new Error('setup missing');
    const api = await authedRequest(playwright, sharedUser.token);
    try {
      // Seed a probe chunk we fully control, then update it. Keeps the test
      // independent of the PDF-derived chunk set.
      const seedText = `e2e-chunks-update-seed-${Date.now()}`;
      const addRes = await api.post('/api/add_chunk', {
        data: { id: sharedSourceId, text: seedText },
      });
      expect(addRes.status()).toBe(201);
      const addBody = (await addRes.json()) as {
        chunk_id: string | string[];
      };
      const seedChunkId = Array.isArray(addBody.chunk_id)
        ? addBody.chunk_id[0]
        : addBody.chunk_id;
      expect(seedChunkId).toBeTruthy();

      const newText = `e2e-chunks-updated-${Date.now()}`;
      const updateRes = await api.put('/api/update_chunk', {
        data: {
          id: sharedSourceId,
          chunk_id: seedChunkId,
          text: newText,
        },
      });
      expect(
        updateRes.status(),
        `update_chunk failed: ${await updateRes.text()}`,
      ).toBe(200);

      const after = await fetchChunks(api, sharedSourceId, { perPage: 100 });
      // Old chunk text is gone.
      expect(after.chunks.some((c) => c.text === seedText)).toBe(false);
      // New chunk text is visible.
      expect(after.chunks.some((c) => c.text === newText)).toBe(true);
    } finally {
      await api.dispose();
    }
  });

  test('DELETE /api/delete_chunk removes the chunk; get_chunks no longer lists it', async () => {
    if (!sharedUser || !sharedSourceId) throw new Error('setup missing');
    const api = await authedRequest(playwright, sharedUser.token);
    try {
      const probeText = `e2e-chunks-delete-${Date.now()}`;
      const addRes = await api.post('/api/add_chunk', {
        data: { id: sharedSourceId, text: probeText },
      });
      expect(addRes.status()).toBe(201);
      const addBody = (await addRes.json()) as {
        chunk_id: string | string[];
      };
      const chunkId = Array.isArray(addBody.chunk_id)
        ? addBody.chunk_id[0]
        : addBody.chunk_id;

      const delRes = await api.delete(
        `/api/delete_chunk?id=${sharedSourceId}&chunk_id=${encodeURIComponent(
          chunkId,
        )}`,
      );
      expect(delRes.status()).toBe(200);

      const after = await fetchChunks(api, sharedSourceId, { perPage: 100 });
      expect(after.chunks.some((c) => c.text === probeText)).toBe(false);
    } finally {
      await api.dispose();
    }
  });

  test('GET /api/get_chunks 404s for a source the caller does not own', async ({
    browser,
  }) => {
    if (!sharedUser || !sharedSourceId) throw new Error('setup missing');
    // Cross-tenant — a fresh JWT whose sub !== sharedUser.sub must be
    // denied access to the shared source row.
    const outsider = signJwt(`outsider-${Date.now()}`);
    const api = await authedRequest(playwright, outsider);
    try {
      const res = await api.get(
        `/api/get_chunks?id=${sharedSourceId}&page=1&per_page=10`,
      );
      expect(res.status()).toBe(404);
    } finally {
      await api.dispose();
    }
    // Silence the unused-browser-fixture eslint; Playwright requires the
    // fixture in the destructured signature to attach tracing.
    void browser;
  });
});
