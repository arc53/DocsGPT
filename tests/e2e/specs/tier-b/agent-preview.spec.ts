/**
 * Tier-B · agent preview persists a HIDDEN conversation
 *
 * Covers B14. The preview flow in `frontend/src/agents/agentPreviewSlice.ts`
 * calls `handleFetchAnswerSteaming(..., save_conversation=false)`. As of the
 * conversation-visibility change, `save_conversation` no longer gates
 * persistence — it controls sidebar visibility only. A preview turn therefore
 * persists a `conversations` row with `visibility = 'hidden'` (decided by
 * `resolve_persistence` in
 * application/api/answer/services/persistence_policy.py and threaded through
 * `BaseAnswerResource.complete_stream(visibility=...)`).
 *
 * The load-bearing assertion is: after a preview stream completes, the row
 * exists but is `hidden`, so it is excluded from the sidebar query
 * (`ConversationsRepository.list_for_user`, which filters `visibility =
 * 'listed'`). If a regression flips the preview default to `listed`, preview
 * traffic would pollute the user's sidebar history.
 *
 * API-driven: the frontend preview UI ultimately POSTs /stream with
 * `save_conversation:false` and `conversation_id:null`; we exercise that
 * contract directly to keep the spec fast and isolated from the AgentPreview
 * modal's rendering quirks. A standard chat POST (save_conversation omitted)
 * is the control — it writes a `listed` row that DOES surface in the sidebar.
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

/** Conversations that surface in the sidebar (the `list_for_user` filter). */
async function countListedConversations(userSub: string): Promise<number> {
  const { rows } = await pg.query<{ n: string }>(
    `SELECT count(*)::text AS n FROM conversations
      WHERE user_id = $1 AND visibility = 'listed'`,
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
 * stream emits `{type:"id", id:"<uuid>"}` once the (hidden) conversation is
 * persisted. Sidebar membership is asserted via the DB helpers below rather
 * than the stream id, so we just drain the response and assert 200.
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

  test('preview stream with save_conversation=false persists a hidden conversation excluded from the sidebar', async ({
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

      // The turn persists (a row + messages exist)...
      expect(
        await countUserConversations(sub),
        'preview stream persists a conversation row',
      ).toBe(1);
      expect(
        await countConversationMessages(sub),
        'preview stream persists conversation_messages rows',
      ).toBeGreaterThan(0);
      // ...but it is hidden, so the sidebar query returns nothing.
      expect(
        await countListedConversations(sub),
        'preview conversation must not surface in the sidebar',
      ).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('control: a non-preview stream (save_conversation omitted) writes a LISTED conversations row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const agentId = await createDraftAgent(sub, 'non-preview-target');
      expect(await countUserConversations(sub)).toBe(0);

      // Standard chat path — save_conversation omitted, so a first-party
      // interactive turn defaults to `listed` (resolve_persistence). This is
      // the "control" that makes the preview assertion meaningful: without
      // it, a spec where nothing ever surfaces could pass trivially.
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

      // Exactly one conversation row landed, and it surfaces in the sidebar.
      expect(await countUserConversations(sub)).toBe(1);
      expect(await countListedConversations(sub)).toBe(1);
      expect(await countConversationMessages(sub)).toBeGreaterThan(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('multiple preview turns persist hidden rows that never surface in the sidebar', async ({
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

      // Each turn persisted its own hidden conversation...
      expect(await countUserConversations(sub)).toBe(3);
      // ...yet the sidebar stays empty no matter how many "Test message"
      // clicks the user makes.
      expect(await countListedConversations(sub)).toBe(0);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
