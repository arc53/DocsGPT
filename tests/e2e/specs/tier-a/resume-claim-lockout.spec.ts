/**
 * Duplicate `tool_actions` resume — the abandoned-claim lockout.
 *
 * Production incident (2026-08-19, four occurrences for one brand-new user at
 * 15:01:17, 15:02:40, 15:13:46 and 15:23:47 UTC — note the ~11 and ~10 minute
 * spacing). Each attempt to resume a paused tool turn came back as:
 *
 *     ERROR /stream - error: Malformed request body - specific error: Resume
 *     already in progress for this conversation. - traceback: ...
 *
 * Three defects compound here:
 *
 * 1. `ResumeInProgressError` subclasses `ValueError`
 *    (application/api/answer/services/continuation_service.py:34), so on
 *    `/stream` it lands in the generic `except ValueError` handler and is
 *    reported to the client as **400 "Malformed request body"** and logged at
 *    ERROR with a full traceback. The correct handling already exists one route
 *    over — `/v1/chat/completions` catches it explicitly and answers **409**
 *    `{"type":"conflict_error","code":"resume_in_progress"}`
 *    (application/api/v1/routes.py:422-433). It was simply never mirrored;
 *    `git log -S ResumeInProgressError -- .../routes/stream.py` is empty.
 *
 * 2. Nothing releases the claim when the client goes away.
 *    `PendingToolStateRepository.claim_state` flips the row `pending →
 *    resuming` atomically, and the only recovery is
 *    `revert_stale_resuming(grace_seconds=600)` from a beat task — so an
 *    abandoned claim locks the conversation for up to **ten minutes**, which is
 *    exactly the spacing in the production timestamps.
 *
 * 3. The client abandons claims by design: `submitToolActions`
 *    (frontend/src/conversation/conversationSlice.ts) opens with
 *    `abortController.abort()` and re-POSTs, and mints a *fresh*
 *    Idempotency-Key each time — which `/stream` does not read anyway.
 *
 * // Silent-break covered: a user who abandons one resume is locked out of
 *    their own conversation for ten minutes and is told their request was
 *    malformed. The seeded `status='resuming'` row below is precisely the state
 *    the app leaves behind when a resume POST is aborted mid-flight.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { open, stat } from 'node:fs/promises';

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';
import { streamOnce } from '../../helpers/streaming.js';

/**
 * Insert the row the app itself writes when a turn pauses for a client-side
 * tool, already claimed — i.e. a resume that was started and then abandoned.
 */
async function seedAbandonedClaim(conversationId: string, userId: string): Promise<void> {
  await pg.query(
    `INSERT INTO pending_tool_state (
        conversation_id, user_id, messages, pending_tool_calls,
        tools_dict, tool_schemas, agent_config, expires_at,
        status, resumed_at
     ) VALUES (
        CAST($1 AS uuid), $2, '[]'::jsonb, '[]'::jsonb,
        '{}'::jsonb, '[]'::jsonb, '{}'::jsonb,
        clock_timestamp() + interval '30 minutes',
        'resuming', clock_timestamp()
     )`,
    [conversationId, userId],
  );
}

/** Byte length of the Flask log, or 0 when it is not present. */
async function readLogSize(path: string): Promise<number> {
  try {
    return (await stat(path)).size;
  } catch {
    return 0;
  }
}

/** Everything appended to the Flask log since `offset`. */
async function readLogSince(path: string, offset: number): Promise<string> {
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

test.describe('duplicate tool_actions resume', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a resume against an already-claimed conversation is a 409 conflict, not a bad request', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    try {
      // A real conversation to resume against.
      const conversationId = await streamOnce(api, {
        question: 'hello',
        save_conversation: true,
      });
      await seedAbandonedClaim(conversationId, sub);

      const res = await api.post('/stream', {
        data: {
          question: '',
          conversation_id: conversationId,
          tool_actions: [{ call_id: 'call_abandoned', decision: 'approved' }],
        },
      });

      // A conflict, matching what /v1/chat/completions has answered since
      // 2026-07-13 — not the "Malformed request body" 400 this used to give.
      expect(res.status()).toBe(409);
      const text = await res.text();
      expect(text).not.toContain('Malformed request body');
      expect(text).toContain('Resume already in progress');

      // The claim is untouched, so every retry inside the 600s grace window
      // gets the same answer — the ten-minute lockout.
      const { rows } = await pg.query<{ status: string }>(
        `SELECT status FROM pending_tool_state WHERE conversation_id = CAST($1 AS uuid)`,
        [conversationId],
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].status).toBe('resuming');
    } finally {
      await api.dispose();
    }
  });

  test('the conflict is logged as a warning, without a traceback', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    const logPath = process.env.E2E_FLASK_LOG ?? '/tmp/docsgpt-e2e/flask.log';
    const before = await readLogSize(logPath);

    try {
      const conversationId = await streamOnce(api, {
        question: 'hello',
        save_conversation: true,
      });
      await seedAbandonedClaim(conversationId, sub);

      await api.post('/stream', {
        data: {
          question: '',
          conversation_id: conversationId,
          tool_actions: [{ call_id: 'call_abandoned', decision: 'approved' }],
        },
      });

      const written = await readLogSince(logPath, before);

      // Racing a resume is an expected concurrency outcome, not a server
      // fault. Logging it as ERROR-with-traceback is what buried it among real
      // errors for a full day in production, so the shape of the log line is
      // part of the contract.
      expect(written).toContain('resume already in progress for conversation');
      expect(written).not.toContain(
        '/stream - error: Malformed request body - specific error: ' +
          'Resume already in progress',
      );
      expect(written).not.toContain('resume_from_tool_actions');
    } finally {
      await api.dispose();
    }
  });
});
