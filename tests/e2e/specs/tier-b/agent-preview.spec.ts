/**
 * Phase 3 Tier-B · agent preview does NOT persist conversations
 *
 * Covers B14. The preview flow in `frontend/src/agents/agentPreviewSlice.ts`
 * calls `handleFetchAnswerSteaming(..., save_conversation=false)` — see the
 * `false` positional arg at line 126. That flag flows through
 * `POST /stream` (application/api/answer/routes/stream.py:55-59,142) into
 * `BaseAnswerResource.complete_stream(should_save_conversation=...)`
 * (application/api/answer/routes/base.py:174,290,389,479), where the
 * branches that insert `conversations` / `conversation_messages` rows are
 * gated on `should_save_conversation`.
 *
 * The load-bearing assertion is: after a preview stream completes, the
 * `conversations` table still has zero rows for this user. If a
 * regression drops the `save_conversation` flag (or flips the default),
 * preview traffic would silently pollute the user's sidebar history.
 *
 * API-driven: the frontend preview UI ultimately POSTs /stream with
 * `save_conversation:false` and `conversation_id:null`; we exercise that
 * contract directly to keep the spec fast and isolated from the
 * AgentPreview modal's rendering quirks. A standard chat POST
 * (save_conversation defaulted to true) is included as a control — it
 * MUST write a conversation row, so "preview wrote zero" is a meaningful
 * contrast rather than "nothing ever writes".
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { streamOnce } from '../../helpers/streaming.js';

/**
 * Insert a minimal draft agent owned by `userSub`. Preview works on
 * drafts — the frontend's AgentPreview modal opens over in-progress
 * drafts before publish.
 */
async function createDraftAgent(userSub: string, name: string): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO agents (user_id, name, status, retriever, chunks, agent_type)
     VALUES ($1, $2, 'draft', 'classic', 2, 'classic')
     RETURNING id::text AS id`,
    [userSub, name],
  );
  const id = rows[0]?.id;
  if (!id) throw new Error(`createDraftAgent failed for ${name}`);
  return id;
}

async function countUserConversations(userSub: string): Promise<number> {
  const { rows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n FROM conversations WHERE user_id = $1`,
    [userSub],
  );
  return Number(rows[0]?.n ?? 0);
}

async function countConversationMessages(userSub: string): Promise<number> {
  const { rows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n
       FROM conversation_messages cm
       JOIN conversations c ON c.id = cm.conversation_id
      WHERE c.user_id = $1`,
    [userSub],
  );
  return Number(rows[0]?.n ?? 0);
}

/**
 * POST /stream with save_conversation=false and drain the SSE body. The
 * stream emits `{type:"id", id:"None"}` in preview mode (preview has no
 * conversation_id to echo back) — we can't use `streamOnce` here because
 * that helper insists on a UUID-shaped id. Instead, just drain the
 * response and assert 200.
 */
async function drainStream(
  api: import('@playwright/test').APIRequestContext,
  body: Record<string, unknown>,
): Promise<void> {
  const res = await api.post('/stream', { data: body });
  expect(
    res.status(),
    `/stream expected 200, got ${res.status()} ${await res.text()}`,
  ).toBe(200);
  // Drain so the server finishes its work (including any persistence
  // branches). The SSE body ends with `data: {"type": "end"}`.
  const text = await res.text();
  expect(text).toContain('"type": "end"');
}

test.describe('tier-b · agent preview', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('preview stream with save_conversation=false writes NO conversations row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createDraftAgent(sub, 'preview-target');

      // Pre-state: zero conversations for this user.
      expect(await countUserConversations(sub)).toBe(0);

      // Fire the preview payload that agentPreviewSlice.ts sends. Key
      // fields: save_conversation=false, conversation_id=null, agent_id.
      await drainStream(api, {
        question: 'Hello preview',
        conversation_id: null,
        agent_id: agentId,
        save_conversation: false,
        isNoneDoc: true,
        chunks: '0',
      });

      // Core assertion: preview MUST NOT persist to conversations.
      expect(
        await countUserConversations(sub),
        'preview stream must not write a conversations row',
      ).toBe(0);
      expect(
        await countConversationMessages(sub),
        'preview stream must not write conversation_messages rows',
      ).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('control: a non-preview stream (save_conversation omitted) DOES write a conversations row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createDraftAgent(sub, 'non-preview-target');
      expect(await countUserConversations(sub)).toBe(0);

      // Standard chat path — save_conversation defaults to true at the
      // backend (stream_model field default + get() fallback in stream.py).
      // This is the "control" that makes the preview assertion meaningful:
      // without it, a spec where nothing ever writes could pass trivially.
      const conversationId = await streamOnce(api, {
        question: 'Hello persistence',
        conversation_id: null,
        agent_id: agentId,
        isNoneDoc: true,
        chunks: '0',
      });
      expect(conversationId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );

      // Exactly one conversation row landed.
      expect(await countUserConversations(sub)).toBe(1);
      expect(await countConversationMessages(sub)).toBeGreaterThan(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('multiple preview turns still produce zero conversations rows', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createDraftAgent(sub, 'preview-repeat');
      expect(await countUserConversations(sub)).toBe(0);

      for (const question of ['first', 'second', 'third']) {
        await drainStream(api, {
          question,
          conversation_id: null,
          agent_id: agentId,
          save_conversation: false,
          isNoneDoc: true,
          chunks: '0',
        });
      }

      // Still zero — no preview turn ever persists, regardless of how
      // many times the user clicks "Test message".
      expect(await countUserConversations(sub)).toBe(0);
      expect(await countConversationMessages(sub)).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
