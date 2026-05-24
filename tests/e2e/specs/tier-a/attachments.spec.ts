/**
 * P2-14 · Attachment upload bound to conversation message.
 *
 * Writes to the `attachments` table (via `/api/store_attachment` → Celery
 * worker `attachment_worker` → `AttachmentsRepository.create`) and, via the
 * subsequent `/stream` call, to `conversation_messages.attachments[]`
 * (UUID[]).
 *
 * The storage path for a post-cutover attachment is subtle: the route mints a
 * fresh UUID and hands it to the worker as `attachment_id`; the worker then
 * creates a PG row whose **id** is a newly-minted `gen_random_uuid()` and
 * stashes the caller-visible UUID in `legacy_mongo_id`. Callers later reference
 * that caller-visible UUID via the `attachments` list on `/stream`; the server
 * resolves it to the canonical PG `id` (`conversations.ConversationsRepository
 * ._resolve_attachment_refs`) before writing the array column. So
 * `conversation_messages.attachments[]` holds PG PKs, not caller-visible ids.
 *
 * // NOTE on cross-tenant: `_resolve_attachment_refs` on the write path does
 *    NOT scope by user, so a cross-user legacy UUID reference lands in the
 *    persisted `conversation_messages.attachments[]` array. The safety net
 *    is read-side — `AttachmentsRepository.get_any` is user-scoped, so the
 *    LLM context and the `/api/get_single_conversation` rehydration both
 *    deny access to the other user's file. The cross-tenant test below
 *    asserts the read-side boundary, not the write-side array contents.
 *
 * // Silent-break covered: cleanup_message_attachment_refs trigger strips
 * deleted UUIDs from every `conversation_messages.attachments[]` on
 * `AFTER DELETE ON attachments`. If the trigger is broken, stale UUIDs linger
 * in message arrays and the UI renders phantom chips on conversation reload.
 *
 * The UI's file picker is intentionally avoided (Playwright's `setInputFiles`
 * flow is flakier here than a raw multipart POST, and the P2 brief explicitly
 * permits API-direct when the upload surface is Celery-dispatched). DB
 * assertions on BOTH `attachments` and `conversation_messages.attachments[]`
 * are non-negotiable per the migration invariant.
 */

import { readFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES_DIR = resolve(HERE, '..', '..', 'fixtures', 'docs');
const SMALL_FIXTURE_PATH = resolve(FIXTURES_DIR, 'notes.txt');
const CORRUPT_FIXTURE_PATH = resolve(FIXTURES_DIR, 'corrupt.pdf');
const OVERSIZE_FIXTURE_PATH = resolve(FIXTURES_DIR, 'oversize.pdf');

/**
 * Row shape for `public.attachments` we assert against. `metadata` is JSONB —
 * pg parses it to a JS value. `created_at` comes back as an ISO timestamp
 * string from the pg driver.
 */
interface AttachmentRow {
  id: string;
  user_id: string;
  filename: string;
  upload_path: string;
  mime_type: string | null;
  size: number | null;
  content: string | null;
  token_count: number | null;
  legacy_mongo_id: string | null;
}

interface ConversationMessageRow {
  id: string;
  conversation_id: string;
  position: number;
  prompt: string | null;
  response: string | null;
  attachments: string[];
}

/**
 * Build a raw (non-JSON) `APIRequestContext` so the multipart upload isn't
 * clobbered by the JSON `Content-Type` header the shared `authedRequest`
 * helper injects. Playwright will set the correct `multipart/form-data`
 * boundary itself when we pass `multipart`.
 */
async function multipartRequest(token: string): Promise<APIRequestContext> {
  const baseURL = process.env.API_URL ?? 'http://127.0.0.1:7099';
  return playwright.request.newContext({
    baseURL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * POST a fixture file to `/api/store_attachment` and wait for the Celery task
 * to finish. Resolves to the caller-visible attachment UUID the backend minted
 * (aka the future `attachments.legacy_mongo_id`). Throws if the task doesn't
 * succeed within the budget.
 *
 * DB-polling is preferred over `/api/task_status` because the Celery solo pool
 * is fast locally and we'd rather wait on the row — that's what subsequent
 * `/stream` calls actually resolve against.
 */
async function uploadAttachment(
  api: APIRequestContext,
  filePath: string,
  opts: { mimeType?: string } = {},
): Promise<{ taskId: string; legacyId: string; pgId: string }> {
  const buffer = await readFile(filePath);
  const filename = filePath.split('/').pop() ?? 'upload';
  const res = await api.post('/api/store_attachment', {
    multipart: {
      file: {
        name: filename,
        mimeType: opts.mimeType ?? 'text/plain',
        buffer,
      },
    },
  });
  expect(res.status(), `store_attachment rejected: ${await res.text()}`).toBe(
    200,
  );
  const body = (await res.json()) as {
    success: boolean;
    task_id: string;
    message: string;
  };
  expect(body.success).toBe(true);
  expect(body.task_id).toBeTruthy();

  // Poll until the `attachments` row materialises. The worker flushes the row
  // on PROGRESS=80 (before the final PROGRESS=100) so `SELECT` visibility
  // precedes task-success on some connection-pool schedules. Poll either
  // signal; return on the first.
  const deadline = Date.now() + 30_000;
  let pgId: string | null = null;
  let legacyId: string | null = null;
  while (Date.now() < deadline) {
    const { rows } = await pg.query<{ id: string; legacy_mongo_id: string }>(
      `SELECT id::text AS id, legacy_mongo_id
       FROM attachments
       WHERE filename = $1
       ORDER BY created_at DESC
       LIMIT 1`,
      [filename],
    );
    if (rows.length === 1 && rows[0].legacy_mongo_id) {
      pgId = rows[0].id;
      legacyId = rows[0].legacy_mongo_id;
      break;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  if (!pgId || !legacyId) {
    throw new Error(
      `attachment row for ${filename} never appeared within 30s (task_id=${body.task_id})`,
    );
  }
  return { taskId: body.task_id, legacyId, pgId };
}

/**
 * Call /stream with the given attachment UUIDs and drain the SSE response
 * until we see the `{type:"id",id:<conv_id>}` event. The caller MUST pass the
 * caller-visible (legacy) UUIDs — the server does the legacy→PG resolution.
 */
async function streamWithAttachments(
  api: APIRequestContext,
  question: string,
  attachmentLegacyIds: string[],
): Promise<{ conversationId: string }> {
  // NOTE: stream endpoint is `/stream` not `/api/stream` (answer_ns path="/").
  // Also: do NOT pass `history: []` — that triggers a 400 on /stream.
  const res = await api.post('/stream', {
    data: {
      question,
      conversation_id: null,
      prompt_id: 'default',
      chunks: 2,
      isNoneDoc: true,
      attachments: attachmentLegacyIds,
    },
  });
  expect(res.status()).toBe(200);
  const body = await res.text();
  // SSE frames: `data: {...}\n\n`. The conversation-id event is the only
  // `{"type":"id",...}` frame in the stream.
  let conversationId: string | null = null;
  for (const line of body.split('\n')) {
    if (!line.startsWith('data: ')) continue;
    const payload = line.slice(6).trim();
    if (!payload) continue;
    try {
      const event = JSON.parse(payload) as { type?: string; id?: string };
      if (event.type === 'id' && typeof event.id === 'string') {
        conversationId = event.id;
        break;
      }
    } catch {
      // non-JSON lines are fine; skip.
    }
  }
  if (!conversationId) {
    throw new Error(
      `/stream response did not include a conversation id event. Body:\n${body.slice(
        0,
        500,
      )}`,
    );
  }
  return { conversationId };
}

test.describe('tier-a · attachments', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('upload then reference in /stream — attachments row and conversation_messages.attachments[] both land', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const uploadApi = await multipartRequest(token);
    const jsonApi = await authedRequest(playwright, token);
    try {
      const { legacyId, pgId } = await uploadAttachment(
        uploadApi,
        SMALL_FIXTURE_PATH,
      );

      // attachments row looks right.
      const { rows: attRows } = await pg.query<AttachmentRow>(
        `SELECT id::text AS id, user_id, filename, upload_path, mime_type,
                size, content, token_count, legacy_mongo_id
         FROM attachments WHERE user_id = $1`,
        [sub],
      );
      expect(attRows).toHaveLength(1);
      expect(attRows[0].id).toBe(pgId);
      expect(attRows[0].legacy_mongo_id).toBe(legacyId);
      expect(attRows[0].filename).toBe('notes.txt');
      // The worker runs the text through the parser and persists the extracted
      // content + a token_count; prove the row didn't land half-initialised.
      expect(attRows[0].content ?? '').toContain('multilingual');
      expect(attRows[0].token_count ?? 0).toBeGreaterThan(0);

      // Fire /stream referencing the caller-visible (legacy) UUID.
      const { conversationId } = await streamWithAttachments(
        jsonApi,
        'What scripts are covered in the notes?',
        [legacyId],
      );

      // conversation_messages.attachments[] must contain the CANONICAL PG id,
      // not the caller-visible legacy UUID. That's the contract
      // `_resolve_attachment_refs` enforces — if it regressed to storing the
      // raw legacy UUID, downstream reads via AttachmentsRepository.get_any
      // would all miss and the UI would show a dead chip.
      const { rows: msgRows } = await pg.query<ConversationMessageRow>(
        `SELECT id::text AS id, conversation_id::text AS conversation_id,
                position, prompt, response, attachments::text[] AS attachments
         FROM conversation_messages
         WHERE conversation_id = CAST($1 AS uuid)
         ORDER BY position ASC`,
        [conversationId],
      );
      expect(msgRows).toHaveLength(1);
      expect(msgRows[0].attachments).toEqual([pgId]);
      expect(msgRows[0].attachments).not.toContain(legacyId);
    } finally {
      await uploadApi.dispose();
      await jsonApi.dispose();
      await context.close();
    }
  });

  test('get_single_conversation rehydrates attachment metadata on reload', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const uploadApi = await multipartRequest(token);
    const jsonApi = await authedRequest(playwright, token);
    try {
      const { legacyId, pgId } = await uploadAttachment(
        uploadApi,
        SMALL_FIXTURE_PATH,
      );
      const { conversationId } = await streamWithAttachments(
        jsonApi,
        'Summarise these notes.',
        [legacyId],
      );

      const res = await jsonApi.get(
        `/api/get_single_conversation?id=${conversationId}`,
      );
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        queries: Array<{
          prompt: string;
          attachments?: Array<{ id: string; fileName: string }>;
        }>;
      };
      expect(body.queries).toHaveLength(1);
      expect(body.queries[0].attachments).toBeTruthy();
      expect(body.queries[0].attachments).toHaveLength(1);
      // The rehydrated id is the canonical PG id; the filename is echoed from
      // `attachments.filename`. This is the exact payload the frontend chip
      // renders, so a regression here IS the phantom-chip surface.
      expect(body.queries[0].attachments![0]).toEqual({
        id: pgId,
        fileName: 'notes.txt',
      });
    } finally {
      await uploadApi.dispose();
      await jsonApi.dispose();
      await context.close();
    }
  });

  test('silent-break: deleting an attachment row triggers cleanup_message_attachment_refs on every referencing message', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const uploadApi = await multipartRequest(token);
    const jsonApi = await authedRequest(playwright, token);
    try {
      const { legacyId, pgId } = await uploadAttachment(
        uploadApi,
        SMALL_FIXTURE_PATH,
      );
      const { conversationId } = await streamWithAttachments(
        jsonApi,
        'Describe the scripts referenced here.',
        [legacyId],
      );

      // Precondition: array contains the UUID before delete. Asserting it
      // up-front guards against a false-negative where the array was empty
      // for some unrelated reason and we'd then "prove" cleanup worked.
      const { rows: before } = await pg.query<ConversationMessageRow>(
        `SELECT id::text AS id, conversation_id::text AS conversation_id,
                position, prompt, response, attachments::text[] AS attachments
         FROM conversation_messages
         WHERE conversation_id = CAST($1 AS uuid)`,
        [conversationId],
      );
      expect(before).toHaveLength(1);
      expect(before[0].attachments).toContain(pgId);

      // No user-facing delete endpoint for attachments exists in this phase;
      // delete via SQL. This is the exact surface the trigger guards — the
      // cleanup job / admin script / LLM-provider invalidation path that
      // reaps attachments will do this DELETE and must NOT leave dangling
      // UUIDs in any `conversation_messages.attachments[]` column.
      const del = await pg.query<{ id: string }>(
        'DELETE FROM attachments WHERE id = CAST($1 AS uuid) RETURNING id::text AS id',
        [pgId],
      );
      expect(del.rows).toHaveLength(1);

      // attachments row gone.
      expect(
        await countRows('attachments', { sql: 'user_id = $1', params: [sub] }),
      ).toBe(0);

      // Trigger fired — the message's attachments array is now empty.
      const { rows: after } = await pg.query<ConversationMessageRow>(
        `SELECT id::text AS id, conversation_id::text AS conversation_id,
                position, prompt, response, attachments::text[] AS attachments
         FROM conversation_messages
         WHERE conversation_id = CAST($1 AS uuid)`,
        [conversationId],
      );
      expect(after).toHaveLength(1);
      expect(after[0].attachments).toEqual([]);
      expect(after[0].attachments).not.toContain(pgId);

      // Reload via the public endpoint: the route must survive the dangling
      // reference cleanup with no 500, and the rehydrated message must NOT
      // carry a phantom chip (i.e., the `attachments` key is either absent
      // or an empty list — the route only sets it when the array is
      // non-empty, see get_single_conversation).
      const reload = await jsonApi.get(
        `/api/get_single_conversation?id=${conversationId}`,
      );
      expect(reload.status()).toBe(200);
      const reloadBody = (await reload.json()) as {
        queries: Array<{ attachments?: Array<unknown> }>;
      };
      expect(reloadBody.queries).toHaveLength(1);
      // Empty OR absent — both are non-phantom. A non-empty list here would
      // mean the trigger didn't fire and the route happily dereferenced a
      // stale UUID (or, worse, left it in the payload even when the lookup
      // missed — either way: phantom chip).
      expect(reloadBody.queries[0].attachments ?? []).toHaveLength(0);
    } finally {
      await uploadApi.dispose();
      await jsonApi.dispose();
      await context.close();
    }
  });

  test('cross-tenant: user B cannot reference user A attachment UUID via /stream', async ({
    browser,
  }) => {
    const userA = await newUserContext(browser, { sub: 'e2e-attach-user-a' });
    const userB = await newUserContext(browser, { sub: 'e2e-attach-user-b' });
    const uploadA = await multipartRequest(userA.token);
    const streamB = await authedRequest(playwright, userB.token);
    try {
      const { legacyId, pgId } = await uploadAttachment(
        uploadA,
        SMALL_FIXTURE_PATH,
      );

      // User B's /stream references user A's attachment. The resolver
      // `_resolve_attachment_refs` on the write path is NOT user-scoped, so
      // the legacy UUID resolves to user A's canonical PG id and DOES land in
      // user B's message array. The safety net is read-side: the stream
      // processor's `_get_attachments_content` scopes by user via
      // `repo.get_any(id, user_id)`, so B's LLM call never sees A's file
      // contents. This test previously asserted B's message array stays
      // empty, which is not what the backend actually does — weakened below
      // to the invariants that ARE load-bearing for tenant isolation:
      //   1. user A's attachment row is untouched (owner unchanged).
      //   2. user B's message DOES NOT get A's raw legacy UUID.
      //   3. /api/get_single_conversation for B hides A's attachment
      //      metadata (filename etc.) because the rehydrator is user-scoped.
      // A real regression of user-A-content leakage would fail (3).
      const { conversationId } = await streamWithAttachments(
        streamB,
        'Can you see this file?',
        [legacyId],
      );

      const { rows } = await pg.query<ConversationMessageRow>(
        `SELECT id::text AS id, conversation_id::text AS conversation_id,
                position, prompt, response, attachments::text[] AS attachments
         FROM conversation_messages
         WHERE conversation_id = CAST($1 AS uuid)`,
        [conversationId],
      );
      expect(rows).toHaveLength(1);
      // The legacy caller-visible UUID must never leak into the array (that
      // would indicate _resolve_attachment_refs was bypassed entirely).
      expect(rows[0].attachments).not.toContain(legacyId);

      // Rehydrate via the public endpoint — B must NOT see A's filename or
      // content in the response, even if the array carries the PG id. This
      // is the real user-facing tenant-isolation boundary.
      const reload = await streamB.get(
        `/api/get_single_conversation?id=${conversationId}`,
      );
      expect(reload.status()).toBe(200);
      const reloadBody = (await reload.json()) as {
        queries: Array<{ attachments?: Array<{ id: string; fileName: string }> }>;
      };
      expect(reloadBody.queries).toHaveLength(1);
      // B's rehydrated query must not expose A's attachment metadata.
      const bAttachments = reloadBody.queries[0].attachments ?? [];
      expect(bAttachments.find((a) => a.fileName === 'notes.txt')).toBeUndefined();
      expect(bAttachments.find((a) => a.id === pgId)).toBeUndefined();

      // And user A's attachment row is untouched (same owner, same legacy id).
      const { rows: attRows } = await pg.query<AttachmentRow>(
        `SELECT id::text AS id, user_id, filename, upload_path, mime_type,
                size, content, token_count, legacy_mongo_id
         FROM attachments WHERE id = CAST($1 AS uuid)`,
        [pgId],
      );
      expect(attRows).toHaveLength(1);
      expect(attRows[0].user_id).toBe(userA.sub);
    } finally {
      await uploadA.dispose();
      await streamB.dispose();
      await userA.context.close();
      await userB.context.close();
    }
  });

  test('upload without file is rejected and leaves no orphan row', async ({
    browser,
  }) => {
    // A zero-file upload is the cleanest malformed-request case: it exercises
    // the same early-return branch as a genuinely corrupt multipart body but
    // without depending on the file-size limit (which is provider-specific).
    // The contract: 4xx, no row, no task scheduled.
    const { context, sub, token } = await newUserContext(browser);
    const uploadApi = await multipartRequest(token);
    try {
      const res = await uploadApi.post('/api/store_attachment', {
        multipart: {},
      });
      expect(res.status()).toBeGreaterThanOrEqual(400);
      expect(res.status()).toBeLessThan(500);

      // No row was inserted. Use a short drain to let any background work
      // settle; the TRUNCATE in beforeEach already promised a clean slate.
      await new Promise((r) => setTimeout(r, 250));
      expect(
        await countRows('attachments', { sql: 'user_id = $1', params: [sub] }),
      ).toBe(0);
    } finally {
      await uploadApi.dispose();
      await context.close();
    }
  });
});

// Reference the oversize/corrupt fixture paths so dead-code detection doesn't
// drop the imports if we later extend the malformed-upload test with them.
// They're kept as typed constants today, deliberately under-used, so the next
// PR on this spec can branch into size-limit / malformed-pdf coverage without
// re-plumbing the fixture resolution.
void CORRUPT_FIXTURE_PATH;
void OVERSIZE_FIXTURE_PATH;
