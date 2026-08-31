/**
 * Failed turns are replayed into the next attempt — why an over-budget
 * conversation cannot recover.
 *
 * Production incident (2026-08-20): a conversation crossed the model's context
 * window and five further sends over 27 minutes each failed identically. The
 * compression threshold checker counted 561,822 → 957,474 → 1,353,246 →
 * 1,748,855 tokens across those attempts — **+395.7k every time, constant to
 * within 200 tokens** — because each attempt that produced no answer was still
 * persisted, and then replayed by the next one.
 *
 * The mechanism is a single missing predicate.
 * `ConversationsRepository.get_messages`
 * (application/storage/db/repositories/conversations.py:633-642) is a bare
 * `SELECT * FROM conversation_messages ... ORDER BY position` with no `status`
 * filter, and it is the ONE query behind both consumers: the agent's history
 * builder and the compression token counter. A `failed` row qualifies for
 * replay in `BaseAgent._build_messages` because the gate is
 * `has_completed_turn = "prompt" in i and "response" in i` (base.py:987) — and
 * the failed row does have a response: the 62-byte
 * `TERMINATED_RESPONSE_PLACEHOLDER`.
 *
 * // Silent-break covered: nothing in the API response reveals this. The proof
 *    has to come from what the provider actually received, so these specs read
 *    the mock LLM's own request log rather than the SSE body.
 *
 * Note the production rows were five NEW sends, not five retry-button presses:
 * the retry path passes `index` and calls `truncate_after(keep_up_to=index-1)`,
 * which deletes the failed row and reuses its position. Five accumulated rows
 * at five distinct positions can only be fresh appends — which is what the
 * generic "Please try again later" error trains a user to do.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { open, stat } from 'node:fs/promises';

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';
import { streamOnce } from '../../helpers/streaming.js';

/** application/api/answer/services/conversation_service.py:32-34 */
const TERMINATED_PLACEHOLDER =
  'Response was terminated prior to completion, try regenerating.';

const MOCK_LLM_LOG = process.env.E2E_MOCK_LLM_LOG ?? '/tmp/docsgpt-e2e/mock-llm.log';

async function logSize(path: string): Promise<number> {
  try {
    return (await stat(path)).size;
  } catch {
    return 0;
  }
}

async function logSince(path: string, offset: number): Promise<string> {
  const handle = await open(path, 'r');
  try {
    const size = (await handle.stat()).size;
    if (size <= offset) return '';
    const buffer = Buffer.alloc(size - offset);
    await handle.read(buffer, 0, buffer.length, offset);
    return buffer.toString('utf8');
  } finally {
    await handle.close();
  }
}

/**
 * Append a turn that produced no answer, exactly as the stream's failure path
 * leaves it: the user's whole question retained in `prompt`, the placeholder
 * in `response`, `status='failed'`.
 */
async function appendFailedTurn(
  conversationId: string,
  userId: string,
  question: string,
): Promise<void> {
  await pg.query(
    `INSERT INTO conversation_messages (
        conversation_id, position, prompt, response, status, user_id, timestamp
     )
     SELECT CAST($1 AS uuid),
            COALESCE(MAX(position), -1) + 1,
            $3, $4, 'failed', $2, clock_timestamp()
       FROM conversation_messages
      WHERE conversation_id = CAST($1 AS uuid)`,
    [conversationId, userId, question, TERMINATED_PLACEHOLDER],
  );
}

test.describe('failed turns in conversation history', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a turn that produced no answer is replayed to the model on the next send', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    // Distinctive enough to find verbatim in the provider request log.
    const deadQuestion = 'DEAD-TURN-MARKER-8f21 summarise the attached dump';

    try {
      const conversationId = await streamOnce(api, {
        question: 'first question',
        save_conversation: true,
      });
      await appendFailedTurn(conversationId, sub, deadQuestion);

      const before = await logSize(MOCK_LLM_LOG);
      await api.post('/stream', {
        data: {
          question: 'second question',
          conversation_id: conversationId,
          save_conversation: true,
        },
      });
      const sent = await logSince(MOCK_LLM_LOG, before);

      // The dead turn was shipped to the provider — both halves of it: the
      // user's full question, and the placeholder standing in for an answer
      // that never existed. It contributes nothing and costs its full length
      // in every subsequent turn.
      expect(sent).toContain('DEAD-TURN-MARKER-8f21');
      expect(sent).toContain('Response was terminated prior to completion');
    } finally {
      await api.dispose();
    }
  });

  test('each additional failed turn adds its full question to the next request', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    // ~40 KB per dead turn: small enough to keep the spec fast, large enough
    // that the growth is unambiguous. Production's were ~965 KB each.
    const filler = 'x'.repeat(40_000);

    try {
      const conversationId = await streamOnce(api, {
        question: 'first question',
        save_conversation: true,
      });

      const sizes: number[] = [];
      for (let round = 0; round < 3; round += 1) {
        await appendFailedTurn(conversationId, sub, `DEAD-${round} ${filler}`);
        const before = await logSize(MOCK_LLM_LOG);
        await api.post('/stream', {
          data: {
            question: `probe ${round}`,
            conversation_id: conversationId,
            save_conversation: true,
          },
        });
        sizes.push((await logSince(MOCK_LLM_LOG, before)).length);
      }

      // Strictly increasing, by roughly one dead question each round: the
      // conversation gets bigger every time an attempt fails, so a user who
      // re-sends after a context-window error is making it worse. This is what
      // eventually put compression's OWN input past the compressor's window
      // (application/api/answer/services/compression/orchestrator.py:174-176
      // compresses every query with no size check), killing the only path that
      // could have rescued the conversation.
      expect(sizes[1]).toBeGreaterThan(sizes[0]);
      expect(sizes[2]).toBeGreaterThan(sizes[1]);
      expect(sizes[2] - sizes[0]).toBeGreaterThan(60_000);
    } finally {
      await api.dispose();
    }
  });
});
