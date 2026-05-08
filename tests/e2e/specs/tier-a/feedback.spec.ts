/**
 * Phase 2 — P2-05 · Message feedback.
 *
 * Writes to the JSONB `conversation_messages.feedback` column. The separate
 * `feedback` table planned in early Phase 1 was dropped during Phase 3
 * hardening — see migration-postgres.md §2.2:
 *     "A dedicated `feedback` table was originally planned for this tier
 *      (and built in early Phase 1) but dropped during Phase 3 hardening:
 *      per-message feedback lives on `conversation_messages.feedback` (JSONB)
 *      via `ConversationsRepository.set_feedback`, and the standalone table
 *      was never populated or read."
 *
 * // Silent-break covered: feedback on index 0 lands on first message, not second
 *
 * The migration-critical silent-break: the frontend passes `prompt_index` to
 * `handleSendFeedback` (conversationHandlers.ts:510-536), which is forwarded
 * verbatim to the `/api/feedback` endpoint as `question_index`. The backend
 * route `SubmitFeedback.post` (application/api/user/conversations/routes.py)
 * passes it to `ConversationsRepository.set_feedback(conv_id, position, ...)`
 * which runs `UPDATE ... WHERE conversation_id = ... AND position = :pos`.
 *
 * If the frontend counted user turns starting from 1 while the backend stored
 * positions starting from 0 (or vice versa), a thumbs-up on the FIRST message
 * would write feedback to the SECOND message and the user would see the
 * thumbs-up on the wrong row after a reload. The fact that the JSONB column
 * replaced the separate `feedback` table makes this worse — there's no
 * intermediate audit surface, the write is just silently misfiled.
 *
 * We prove positional correctness by creating a 2-message conversation,
 * submitting feedback at `question_index=0`, and asserting the JSONB landed
 * on the row where `position=0` AND is NULL on the row where `position=1`.
 *
 * Seeding strategy: we drive the `/stream` endpoint twice via the
 * authed `APIRequestContext`. First call creates the conversation (emits the
 * new conversation_id as a `{"type":"id"}` SSE event) and appends message at
 * position 0. Second call (with that conversation_id) appends at position 1.
 * UI chat flow is covered by P2-07, not here; this spec is API-only so we
 * can exercise the exact positional contract the UI depends on.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface MessageRow {
  position: number;
  prompt: string | null;
  response: string | null;
  // pg parses JSONB to JS values; `null` or `{text, timestamp}`.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  feedback: any;
}

/**
 * Parse the conversation id out of a buffered SSE response body. The Flask
 * stream emits a `{"type": "id", "id": "<uuid>"}` event exactly once per
 * successful turn (application/api/answer/routes/base.py:362 and :430).
 * When called on an existing conversation the id echoes back unchanged; when
 * called without a conversation_id it surfaces the newly-minted UUID.
 */
function extractConversationId(body: string): string {
  const lines = body.split('\n');
  for (const raw of lines) {
    const line = raw.trim();
    if (!line.startsWith('data:')) continue;
    const json = line.slice('data:'.length).trim();
    if (!json) continue;
    try {
      const evt = JSON.parse(json) as { type?: string; id?: string };
      if (evt.type === 'id' && typeof evt.id === 'string' && evt.id.length > 0) {
        return evt.id;
      }
    } catch {
      // non-JSON SSE line — skip
    }
  }
  throw new Error(
    `No {"type":"id"} event in stream body — got:\n${body.slice(0, 400)}`,
  );
}

/**
 * Post a single /stream turn and return the conversation id the backend
 * persisted. Buffers the entire SSE response via Playwright's
 * `APIRequestContext.post` (Flask closes the stream when the generator
 * returns, so the body arrives complete).
 */
async function streamTurn(
  api: APIRequestContext,
  question: string,
  conversationId?: string,
): Promise<string> {
  const payload: Record<string, unknown> = {
    question,
    isNoneDoc: true,
    save_conversation: true,
    retriever: 'classic',
  };
  if (conversationId) {
    payload.conversation_id = conversationId;
  }
  // NOTE: deliberately NOT passing `history: []` — the /stream route 400s on
  // an empty-array history (see application/api/answer/routes/stream.py).
  // New conversations are implied when `conversation_id` is absent.
  const res = await api.post('/stream', {
    data: payload,
    // Streaming turns go through the mock LLM; allow generous budget.
    timeout: 30_000,
  });
  expect(res.status()).toBe(200);
  const body = await res.text();
  return extractConversationId(body);
}

/**
 * Seed a conversation with exactly two message pairs. Returns the PG UUID of
 * the conversation. Verified against `conversation_messages` so the tests
 * below can trust `position=0` and `position=1` both exist before acting.
 */
async function seedTwoMessageConversation(
  api: APIRequestContext,
  userId: string,
): Promise<string> {
  const convId = await streamTurn(api, 'first question for feedback positional test');
  const echoId = await streamTurn(api, 'second question for feedback positional test', convId);
  expect(echoId).toBe(convId);

  // Confirm our seed actually produced positions 0 and 1 for this user.
  const { rows } = await pg.query<{ position: number }>(
    'SELECT position FROM conversation_messages '
      + 'WHERE conversation_id = CAST($1 AS uuid) AND user_id = $2 '
      + 'ORDER BY position ASC',
    [convId, userId],
  );
  expect(rows.map((r) => r.position)).toEqual([0, 1]);
  return convId;
}

test.describe('tier-a · message feedback', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('thumbs-up at question_index=0 lands on position=0 (not position=1)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await seedTwoMessageConversation(api, sub);

      const res = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: 'like',
        },
      });
      expect(res.status()).toBe(200);
      const body = (await res.json()) as { success: boolean };
      expect(body.success).toBe(true);

      // THE silent-break assertion: index 0 writes to position 0, and the
      // row at position 1 remains untouched. If the off-by-one bug were
      // live, `feedback` would be NULL at position 0 and non-null at
      // position 1, and this test would fail on both clauses.
      const { rows } = await pg.query<MessageRow>(
        'SELECT position, prompt, response, feedback '
          + 'FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) '
          + 'ORDER BY position ASC',
        [convId],
      );
      expect(rows).toHaveLength(2);

      const first = rows[0];
      expect(first.position).toBe(0);
      expect(first.feedback).not.toBeNull();
      expect(first.feedback?.text).toBe('like');
      expect(typeof first.feedback?.timestamp).toBe('string');

      const second = rows[1];
      expect(second.position).toBe(1);
      expect(second.feedback).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('thumbs-down overwrites (replaces the JSONB, does not merge keys)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await seedTwoMessageConversation(api, sub);

      // First write: like.
      const likeRes = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: 'like',
        },
      });
      expect(likeRes.status()).toBe(200);

      const { rows: afterLike } = await pg.query<MessageRow>(
        'SELECT feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) AND position = 0',
        [convId],
      );
      expect(afterLike[0].feedback?.text).toBe('like');
      const firstTimestamp = afterLike[0].feedback?.timestamp as string;
      expect(typeof firstTimestamp).toBe('string');

      // Second write: dislike. Must REPLACE the blob, not merge: if the
      // repository naively used `feedback || '{}'::jsonb || :fb` it would
      // leave a stale `text:'like'` key behind.
      const dislikeRes = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: 'dislike',
        },
      });
      expect(dislikeRes.status()).toBe(200);

      const { rows: afterDislike } = await pg.query<MessageRow>(
        'SELECT feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) AND position = 0',
        [convId],
      );
      expect(afterDislike[0].feedback?.text).toBe('dislike');

      // The JSONB has exactly the two keys we put in — no leftover values
      // from the first write.
      expect(Object.keys(afterDislike[0].feedback).sort()).toEqual(
        ['text', 'timestamp'].sort(),
      );

      // The timestamp key is fresh, not carried over from the like write.
      // (Not asserting strict inequality of timestamps — clock resolution
      // can alias them — but they must both be valid ISO strings and the
      // text has definitively changed.)
      expect(typeof afterDislike[0].feedback.timestamp).toBe('string');
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('null feedback clears the JSONB back to NULL', async ({ browser }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await seedTwoMessageConversation(api, sub);

      // Arrange: put a like on position 0.
      const likeRes = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: 'like',
        },
      });
      expect(likeRes.status()).toBe(200);

      // Act: clear with null.
      const clearRes = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: null,
        },
      });
      expect(clearRes.status()).toBe(200);

      // Assert: column is genuinely NULL — not a JSONB `null`, not an empty
      // object. The route's branch at routes.py:281-290 sets the payload to
      // Python `None` when the feedback value is `None`, and
      // `set_feedback` casts `None` → SQL NULL via the JSON serialization.
      const { rows } = await pg.query<MessageRow>(
        'SELECT feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) AND position = 0',
        [convId],
      );
      expect(rows[0].feedback).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('out-of-range question_index does not write or corrupt any row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await seedTwoMessageConversation(api, sub);

      // Snapshot both rows before the stray write.
      const { rows: before } = await pg.query<MessageRow>(
        'SELECT position, feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) '
          + 'ORDER BY position ASC',
        [convId],
      );
      expect(before).toHaveLength(2);
      expect(before[0].feedback).toBeNull();
      expect(before[1].feedback).toBeNull();

      // Act: feedback at a position that doesn't exist on this 2-message
      // conversation.
      const res = await api.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 99,
          feedback: 'like',
        },
      });

      // The route does not validate the index — `set_feedback` runs an
      // UPDATE that simply matches zero rows and returns rowcount=0. Either
      // of two implementations would be acceptable (200 silent-noop, or
      // 4xx explicit rejection). Accept both; the critical invariant is
      // that NO existing row was mutated and NO extra row was appended.
      expect([200, 400, 404, 422]).toContain(res.status());

      const { rows: after } = await pg.query<MessageRow>(
        'SELECT position, feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) '
          + 'ORDER BY position ASC',
        [convId],
      );
      expect(after).toHaveLength(2);
      expect(after[0].position).toBe(0);
      expect(after[0].feedback).toBeNull();
      expect(after[1].position).toBe(1);
      expect(after[1].feedback).toBeNull();
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('cross-tenant: user B cannot leave feedback on user A\'s conversation', async ({
    browser,
  }) => {
    // User A owns the conversation. User B is a separate freshly-minted
    // user, posting `/api/feedback` with A's conversation_id.
    const {
      context: contextA,
      sub: subA,
      token: tokenA,
    } = await newUserContext(browser);
    const {
      context: contextB,
      token: tokenB,
    } = await newUserContext(browser);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const convId = await seedTwoMessageConversation(apiA, subA);

      // Snapshot A's rows — we'll assert byte equality after B's attempt.
      const { rows: before } = await pg.query<MessageRow>(
        'SELECT position, feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) '
          + 'ORDER BY position ASC',
        [convId],
      );
      expect(before).toHaveLength(2);
      expect(before.every((r) => r.feedback === null)).toBe(true);

      // B tries to leave feedback on A's conversation. The route calls
      // `repo.get_any(conversation_id, user_id)` scoped to B's sub — A's
      // row is not in B's ownership set, so the lookup returns None and
      // the route returns 404. (routes.py:294-298.)
      const res = await apiB.post('/api/feedback', {
        data: {
          conversation_id: convId,
          question_index: 0,
          feedback: 'dislike',
        },
      });
      expect(res.status()).toBe(404);
      const body = (await res.json()) as { success: boolean };
      expect(body.success).toBe(false);

      // DB-level assertion — A's rows are still pristine.
      const { rows: after } = await pg.query<MessageRow>(
        'SELECT position, feedback FROM conversation_messages '
          + 'WHERE conversation_id = CAST($1 AS uuid) '
          + 'ORDER BY position ASC',
        [convId],
      );
      expect(after).toHaveLength(2);
      expect(after[0].feedback).toBeNull();
      expect(after[1].feedback).toBeNull();
    } finally {
      await apiA.dispose();
      await apiB.dispose();
      await contextA.close();
      await contextB.close();
    }
  });
});
