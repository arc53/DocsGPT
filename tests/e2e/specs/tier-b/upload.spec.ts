/**
 * Phase 3 Tier-B · upload (B1) — core upload happy paths.
 *
 * Exercises the two ingest entry points the UI drives from
 * `frontend/src/upload/Upload.tsx`:
 *
 *   - POST /api/upload            (multipart file upload → Celery `ingest`)
 *   - POST /api/remote            (form w/ JSON `data` → Celery `ingest_remote`
 *                                  for source=url/github/crawler/reddit/s3/
 *                                  connectors)
 *
 * Plus /api/task_status polling. Each state-changing call is followed by a
 * DB assertion on the `sources` table.
 *
 * URL ingestor choice: we point the `source=url` variant at
 * `http://127.0.0.1:7099/api/config` — a stable always-200 endpoint on the
 * e2e Flask — to avoid external network dependencies. The ingest_remote
 * task invocation + /api/task_status round-trip is what we verify; the
 * actual crawl result is a black box depending on the crawler's user-agent
 * handling, which is out of scope for B1.
 *
 * Known-issue note (not fixed by this spec):
 *   After a successful upload, the `sources.id` minted by
 *   `SourcesRepository.create` is NOT the same UUID as the faiss index
 *   directory the worker wrote (`indexes/<worker-uuid>/`). Chunks lookups
 *   keyed on sources.id therefore 500 — this is why chunks.spec.ts
 *   explicitly seeds a PG row with the faiss directory's UUID rather than
 *   relying on the natural upload flow. We assert the `sources` row exists
 *   here and leave the id-mismatch to B3's harness.
 */

import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { authedRequest } from '../../helpers/api.js';
import {
  multipartContext,
  postRemote,
  postUpload,
  waitForTask,
} from '../../helpers/uploads.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = resolve(HERE, '..', '..', 'fixtures', 'docs');
const SMALL_PDF = resolve(FIXTURES_DIR, 'small.pdf');
const CORRUPT_PDF = resolve(FIXTURES_DIR, 'corrupt.pdf');
const NOTES_TXT = resolve(FIXTURES_DIR, 'notes.txt');

interface SourceSummary {
  id: string;
  user_id: string;
  name: string;
  type: string | null;
  file_path: string | null;
}

async function getSourcesForUser(userId: string): Promise<SourceSummary[]> {
  const { rows } = await pg.query<SourceSummary>(
    `SELECT id::text AS id, user_id, name, type, file_path
     FROM sources WHERE user_id = $1 ORDER BY created_at DESC`,
    [userId],
  );
  return rows;
}

test.describe('tier-b · upload', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('POST /api/upload small.pdf → task runs and sources row exists', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      const taskId = await postUpload(multi, SMALL_PDF, {
        user: sub,
        name: 'small-pdf-upload',
      });
      expect(taskId).toMatch(/^[0-9a-f-]{36}$/i);

      const final = await waitForTask(apiJson, taskId);
      expect(
        final.status,
        `ingest terminal state unexpected: ${JSON.stringify(final)}`,
      ).toBe('SUCCESS');

      // The worker's `upload_index` call triggers `SourcesRepository.create`
      // via /api/upload_index (application/api/internal/routes.py:139). The
      // row is owned by the JWT `sub`, and `file_path` mirrors the storage
      // path for the uploaded artifact.
      const rows = await getSourcesForUser(sub);
      expect(rows).toHaveLength(1);
      expect(rows[0].name).toBe('small-pdf-upload');
      expect(rows[0].type).toBe('local');
      expect(rows[0].file_path).toContain('small-pdf-upload');
    } finally {
      await multi.dispose();
      await apiJson.dispose();
      await context.close();
    }
  });

  test('POST /api/remote url ingestor accepts a valid URL and returns a task_id', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      const taskId = await postRemote(multi, {
        user: sub,
        name: 'url-ingest',
        source: 'url',
        // Pointing at the e2e Flask's own /api/config — always 200, served
        // by this same process, no external dependencies.
        data: { url: 'http://127.0.0.1:7099/api/config' },
      });
      expect(taskId).toMatch(/^[0-9a-f-]{36}$/i);

      // We do not require SUCCESS — the remote worker's URL loader path
      // may fail on the JSON response body (it's not HTML), but the
      // endpoint contract (task_id returned, task_status reachable) is
      // what we're asserting here. Drain to a terminal state either way
      // so we don't leak an in-flight task into the next test.
      const final = await waitForTask(apiJson, taskId, 30_000);
      expect(['SUCCESS', 'FAILURE']).toContain(final.status);
    } finally {
      await multi.dispose();
      await apiJson.dispose();
      await context.close();
    }
  });

  test('POST /api/upload corrupt.pdf → task completes (may SUCCESS with empty docs or FAILURE at parse)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      const taskId = await postUpload(multi, CORRUPT_PDF, {
        user: sub,
        name: 'corrupt-upload',
        mimeType: 'application/pdf',
      });

      const final = await waitForTask(apiJson, taskId, 45_000);
      // The docling PDF pipeline is lenient — a stripped PDF body like our
      // `corrupt.pdf` fixture either parses to an empty doc (SUCCESS with
      // zero chunks) or raises mid-pipeline (FAILURE). Both reflect the
      // API contract truthfully; we only require the task completes and
      // /api/task_status surfaces a stable terminal envelope.
      expect(['SUCCESS', 'FAILURE']).toContain(final.status);
      if (final.status === 'FAILURE') {
        // FAILURE meta is stringified — not a progress dict.
        expect(typeof final.result).toBe('string');
      }
    } finally {
      await multi.dispose();
      await apiJson.dispose();
      await context.close();
    }
  });

  test('POST /api/upload notes.txt with unicode-bearing job name → sources.name stored verbatim', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    const apiJson = await authedRequest(playwright, token);
    try {
      // Unicode + spaces in the *job name* (which becomes sources.name).
      // The backend only applies `safe_filename` to the filesystem dir
      // derivatives — the stored DB name is the raw input.
      const jobName = 'notes-уникод спейсы';
      const taskId = await postUpload(multi, NOTES_TXT, {
        user: sub,
        name: jobName,
        mimeType: 'text/plain',
        filename: 'notes-file.txt',
      });

      const final = await waitForTask(apiJson, taskId);
      expect(final.status).toBe('SUCCESS');

      const rows = await getSourcesForUser(sub);
      expect(rows).toHaveLength(1);
      expect(rows[0].name).toBe(jobName);
    } finally {
      await multi.dispose();
      await apiJson.dispose();
      await context.close();
    }
  });

  test('POST /api/upload with no file field → 400 and no sources row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const multi = await multipartContext(token);
    try {
      // Omit `file` entirely — backend validates via `request.files.getlist`
      // and `check_required_fields` in sources/upload.py:62-71.
      const res = await multi.post('/api/upload', {
        multipart: {
          user: sub,
          name: 'missing-file-job',
        },
      });
      expect(res.status()).toBe(400);

      const rows = await getSourcesForUser(sub);
      expect(rows).toHaveLength(0);
    } finally {
      await multi.dispose();
      await context.close();
    }
  });
});

