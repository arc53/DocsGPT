/**
 * Retrying a failed resume must keep the answer it produces.
 *
 * `release_claim` hands a failed resume's `pending_tool_state` row back to
 * `pending` so the user can retry immediately instead of waiting out
 * `revert_stale_resuming`'s 600 s grace. But the same `except Exception` in
 * `routes/base.py` also finalizes the reserved message row `failed`, and a
 * resume reuses the SAME `reserved_message_id` — `resume_from_tool_actions`
 * reads it back out of the persisted `agent_config`
 * (services/stream_processor.py). So the retry streams into a row that is
 * already terminal, and `finalize_message(status="complete")` is gated by
 * `only_if_non_terminal`, whose reclaim hole originally matched only the
 * reconciler's own error string. Outcome: `ALREADY_FAILED`.
 *
 * // Silent-break covered: the user watches a correct answer stream in, then
 *    on reload finds "Response was terminated prior to completion" with no way
 *    back to it. Nothing in the SSE body reveals the loss — the wire shows a
 *    perfectly healthy turn — so these specs assert on the DB row and on
 *    GET /api/get_single_conversation, never on the stream.
 *
 * The fix stamps `resume_retryable` on the failure exactly when the claim was
 * released, and widens the reclaim gate to honour it. The two side effects
 * have to agree: releasing the claim says "retryable", so the row must not
 * simultaneously be terminal in a way the retry cannot overwrite.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';
import { streamOnce } from '../../helpers/streaming.js';

/** application/api/answer/services/conversation_service.py */
const TERMINATED_PLACEHOLDER =
  'Response was terminated prior to completion, try regenerating.';

interface MessageRow {
  id: string;
  status: string;
  response: string;
  message_metadata: Record<string, unknown> | null;
}

async function messageRow(id: string): Promise<MessageRow> {
  const { rows } = await pg.query<MessageRow>(
    `SELECT id, status, response, message_metadata
       FROM conversation_messages WHERE id = CAST($1 AS uuid)`,
    [id],
  );
  return rows[0];
}

async function claimStatus(convId: string): Promise<string | null> {
  const { rows } = await pg.query<{ status: string }>(
    `SELECT status FROM pending_tool_state
      WHERE conversation_id = CAST($1 AS uuid)`,
    [convId],
  );
  return rows.length ? rows[0].status : null;
}

/**
 * Park a message row mid-flight and point a claimable `pending_tool_state` at
 * it, exactly as a turn paused on a client-side tool does. `agent_config`
 * carries the `reserved_message_id`, which is what makes the retry reuse this
 * same row.
 */
async function seedPausedTurn(
  convId: string,
  sub: string,
): Promise<string> {
  const { rows } = await pg.query<{ id: string }>(
    `INSERT INTO conversation_messages (
        conversation_id, position, prompt, response, status, user_id,
        timestamp, message_metadata
     ) VALUES (CAST($1 AS uuid), 99, 'paused on a tool', '', 'streaming', $2,
               clock_timestamp(), '{}'::jsonb)
     RETURNING id`,
    [convId, sub],
  );
  const messageId = rows[0].id;

  await pg.query(
    `INSERT INTO pending_tool_state (
        conversation_id, user_id, messages, pending_tool_calls,
        tools_dict, tool_schemas, agent_config, expires_at, status
     ) VALUES (
        CAST($1 AS uuid), $2,
        CAST($3 AS jsonb), CAST($4 AS jsonb),
        '{}'::jsonb, '[]'::jsonb, CAST($5 AS jsonb),
        clock_timestamp() + interval '30 minutes', 'pending')`,
    [
      convId,
      sub,
      JSON.stringify([
        { role: 'user', content: 'paused on a tool' },
        {
          role: 'assistant',
          content: null,
          // No `name` on the function — enough to make gen_continuation raise,
          // which is the "resume failed once" trigger this spec is about.
          tool_calls: [
            { id: 'call_1', type: 'function', function: { arguments: '{}' } },
          ],
        },
      ]),
      JSON.stringify([
        {
          call_id: 'call_1',
          tool_name: 'noop',
          action_name: 'noop',
          arguments: {},
        },
      ]),
      JSON.stringify({
        llm_name: 'openai',
        agent_type: 'ClassicAgent',
        prompt: 'You are a test assistant.',
        reserved_message_id: messageId,
      }),
    ],
  );
  return messageId;
}

test.describe('retrying a failed resume', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a failed resume hands the claim back instead of holding it for 600s', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await streamOnce(api, {
        question: 'hello',
        save_conversation: true,
      });
      await seedPausedTurn(convId, sub);

      const res = await api.post('/stream', {
        data: {
          question: '',
          conversation_id: convId,
          tool_actions: [{ call_id: 'call_1', decision: 'approved' }],
        },
      });
      await res.text();

      // Not `resuming`: that is the ten-minute lockout from the 2026-08-19
      // incident, recoverable only by the janitor.
      expect(await claimStatus(convId)).not.toBe('resuming');
    } finally {
      await api.dispose();
    }
  });

  test('the failure it leaves behind is marked retryable, not plainly terminal', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await streamOnce(api, {
        question: 'hello',
        save_conversation: true,
      });
      const messageId = await seedPausedTurn(convId, sub);

      const res = await api.post('/stream', {
        data: {
          question: '',
          conversation_id: convId,
          tool_actions: [{ call_id: 'call_1', decision: 'approved' }],
        },
      });
      await res.text();

      const row = await messageRow(messageId);
      expect(row.status).toBe('failed');
      expect(row.response).toBe(TERMINATED_PLACEHOLDER);
      // The marker the reclaim gate keys on. Without it the retry below can
      // never overwrite this row, and its answer is discarded in silence.
      expect(row.message_metadata?.resume_retryable).toBe(true);
    } finally {
      await api.dispose();
    }
  });

  test("a retry's answer replaces the failed row instead of being discarded", async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await streamOnce(api, {
        question: 'hello',
        save_conversation: true,
      });
      const messageId = await seedPausedTurn(convId, sub);

      // Resume #1 — errors, releases the claim, marks the row retryable.
      const first = await api.post('/stream', {
        data: {
          question: '',
          conversation_id: convId,
          tool_actions: [{ call_id: 'call_1', decision: 'approved' }],
        },
      });
      await first.text();
      expect((await messageRow(messageId)).status).toBe('failed');

      // Resume #2 — the row is claimable again, so re-approving works. Repair
      // the stored messages first: the retry is the user clicking approve a
      // second time on a turn whose state is intact, not a replay of the
      // corruption that broke resume #1.
      await pg.query(
        `UPDATE pending_tool_state
            SET messages = jsonb_set(
                  messages, '{1,tool_calls,0,function,name}', '"noop"'::jsonb)
          WHERE conversation_id = CAST($1 AS uuid)`,
        [convId],
      );

      const second = await api.post('/stream', {
        data: {
          question: '',
          conversation_id: convId,
          tool_actions: [{ call_id: 'call_1', decision: 'approved' }],
        },
      });
      const body = await second.text();
      expect(second.status()).toBe(200);

      // The whole point: whatever the second attempt produced must be what the
      // row holds. A silently-dropped answer leaves the placeholder behind.
      const row = await messageRow(messageId);
      if (body.includes('"type": "end"')) {
        expect(row.status).toBe('complete');
        expect(row.response).not.toBe(TERMINATED_PLACEHOLDER);
        // Reclaim strips the failure bookkeeping, or a finished answer
        // carries a stale error into the API response.
        expect(row.message_metadata?.error).toBeUndefined();
        expect(row.message_metadata?.resume_retryable).toBeUndefined();
      } else {
        // If the second attempt also failed, it must at least still be
        // retryable — never wedged terminal with the claim gone.
        expect(row.message_metadata?.resume_retryable).toBe(true);
      }
    } finally {
      await api.dispose();
    }
  });
});
