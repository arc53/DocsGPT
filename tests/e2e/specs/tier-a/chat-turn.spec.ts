/**
 * Phase 2 — P2-07 · chat turn save (the HOTTEST migration path).
 *
 * A single /stream call is responsible for writes to FOUR Tier-1 tables:
 *
 *   - `conversations`          (1 row per new conversation)
 *   - `conversation_messages`  (1 row per turn — prompt AND response in the
 *                               same row, positions 0, 1, 2, ...)
 *   - `token_usage`            (>=1 row: per-LLM-call insert from the
 *                               stream_token_usage decorator in
 *                               application/usage.py)
 *   - `user_logs`              (>=1 row: the `stream_answer` summary log
 *                               appended at the tail of complete_stream)
 *
 * The migration-critical silent break lives in
 * `ConversationsRepository.append_message`: if the advisory lock
 * (SELECT ... FOR UPDATE on the parent conversations row) is broken, two
 * concurrent /stream calls on the SAME conversation_id race on the
 * COALESCE(MAX(position), -1) + 1 query and both try to insert at the
 * same position. `conversation_messages_conv_pos_uidx` then 500s one of
 * them — a LOST MESSAGE, invisible from the UI since the first turn
 * already returned 200 and the user moved on. This spec pins that lock
 * in place by firing two /stream POSTs via Promise.all and proving
 *   (a) neither returns 500
 *   (b) both resulting turn rows landed at UNIQUE positions
 *
 * Invocation style note: SSE is wrapped by fetch() / APIRequestContext
 * much more cleanly than by a second browser context — we don't need
 * UI events for the concurrency test, only the HTTP response code and
 * the eventual DB state. UI-driven for the happy path only.
 */

// Silent-break covered: two-tab concurrent /stream — no lost message, no unique-constraint 500

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext, Page } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

interface ConversationRow {
  id: string;
  user_id: string;
  name: string | null;
}

interface MessageRow {
  id: string;
  conversation_id: string;
  position: number;
  prompt: string | null;
  response: string | null;
  thought: string | null;
  // pg parses JSONB to JS values
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  sources: any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  tool_calls: any;
}

/**
 * Fetch all `conversation_messages` rows for a user's conversations,
 * ordered by (conversation_id, position). Tests use this for
 * position-uniqueness assertions.
 */
async function fetchMessagesForUser(userId: string): Promise<MessageRow[]> {
  const { rows } = await pg.query<MessageRow>(
    `SELECT cm.id::text AS id,
            cm.conversation_id::text AS conversation_id,
            cm.position,
            cm.prompt,
            cm.response,
            cm.thought,
            cm.sources,
            cm.tool_calls
       FROM conversation_messages cm
       JOIN conversations c ON c.id = cm.conversation_id
      WHERE c.user_id = $1
      ORDER BY cm.conversation_id, cm.position`,
    [userId],
  );
  return rows;
}

async function fetchConversationsForUser(
  userId: string,
): Promise<ConversationRow[]> {
  const { rows } = await pg.query<ConversationRow>(
    `SELECT id::text AS id, user_id, name
       FROM conversations
      WHERE user_id = $1
      ORDER BY created_at ASC`,
    [userId],
  );
  return rows;
}

/**
 * Drive one chat turn through the UI: type ``question`` into the main
 * message textarea, click Send, and wait for the /stream response to
 * complete. Returns the POST body the frontend sent (useful to grab the
 * resulting ``conversation_id`` the stream SSE emitted).
 */
async function sendMessageViaUi(page: Page, question: string): Promise<void> {
  const textarea = page.locator('#message-input');
  await expect(textarea).toBeVisible();
  await textarea.fill(question);

  // Arm the network waiters BEFORE clicking so we don't miss the response.
  // The frontend streams via fetch() to /stream and reads chunks until the
  // server closes; the Playwright Response resolves when the connection
  // closes, which is exactly the "streaming finished" signal we want.
  const streamDonePromise = page.waitForResponse(
    (r) => r.url().includes('/stream') && r.request().method() === 'POST',
    { timeout: 45_000 },
  );

  // The changelog notification banner (bottom-right) sometimes overlaps
  // the Send icon button, intercepting the click. Submit via Enter on the
  // textarea instead — MessageInput.tsx binds Enter (without shift) to
  // handleSubmit, the exact same handler the Send button uses.
  await textarea.press('Enter');

  const streamRes = await streamDonePromise;
  expect(streamRes.status()).toBe(200);

  // Belt-and-braces: the cancel button (shown while loading) must be gone
  // so we know the Redux slice flipped status back to idle.
  await expect(
    page.getByRole('button', { name: /^cancel$/i }),
  ).toBeHidden({ timeout: 15_000 });
}

/**
 * Fire POST /stream directly via an authed request context and consume
 * the SSE body to completion. Returns the final conversation_id seen in
 * the stream's `{"type":"id", ...}` event, plus the raw status code so
 * callers can assert on HTTP 200 vs. 500.
 *
 * We go through fetch() (NOT api.post) because APIRequestContext buffers
 * the entire response before returning, which holds the socket open for
 * the full server-side stream — that's exactly what we need for the
 * concurrency assertion: both /stream handlers must overlap in time.
 */
async function streamDirect(
  token: string,
  body: Record<string, unknown>,
): Promise<{ status: number; conversationId: string | null; text: string }> {
  const res = await fetch(`${API_URL}/stream`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
  const text = await res.text();

  // Extract the last `{"type":"id","id":"..."}` frame — the stream emits
  // one of those after the save_conversation call succeeds.
  let conversationId: string | null = null;
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data: ')) continue;
    const payload = trimmed.slice('data: '.length);
    try {
      const parsed = JSON.parse(payload) as { type?: string; id?: string };
      if (parsed.type === 'id' && typeof parsed.id === 'string') {
        conversationId = parsed.id;
      }
    } catch {
      // non-JSON frame (e.g. heartbeat) — ignore
    }
  }
  return { status: res.status, conversationId, text };
}

test.describe('tier-a · chat turn save', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('single chat turn via UI writes to all four Tier-1 tables and reload rehydrates the conversation', async ({
    browser,
  }) => {
    const { context, sub } = await newUserContext(browser);
    try {
      const page = await context.newPage();
      await page.goto('/');

      // Wait for the shell to render — the message input is the canonical
      // ready signal. (Same wait strategy other Tier-A specs use.)
      await expect(page.locator('#message-input')).toBeVisible();

      const question = 'What is DocsGPT? e2e-p2-07-single-turn';
      await sendMessageViaUi(page, question);

      // ---- DB-level assertions ---------------------------------------

      const conversations = await fetchConversationsForUser(sub);
      expect(conversations).toHaveLength(1);
      const conv = conversations[0];
      expect(conv.user_id).toBe(sub);

      // One turn => one conversation_messages row at position 0, with
      // BOTH prompt (question) and response (answer) populated. Position
      // 0 is load-bearing: the append_message advisory lock would silently
      // break if we saw anything else.
      const messages = await fetchMessagesForUser(sub);
      expect(messages).toHaveLength(1);
      expect(messages[0].conversation_id).toBe(conv.id);
      expect(messages[0].position).toBe(0);
      expect(messages[0].prompt).toBe(question);
      expect(messages[0].response).toBeTruthy();

      // token_usage and user_logs should each have at least one row
      // attributable to this user.
      const tokenCount = await countRows('token_usage', {
        sql: 'user_id = $1',
        params: [sub],
      });
      expect(tokenCount).toBeGreaterThanOrEqual(1);

      const userLogCount = await countRows('user_logs', {
        sql: "user_id = $1 AND endpoint = 'stream_answer'",
        params: [sub],
      });
      expect(userLogCount).toBeGreaterThanOrEqual(1);

      // ---- Reload rehydrates conversation in sidebar -----------------
      await page.reload();
      await expect(page.locator('#message-input')).toBeVisible();
      // Conversation tiles use onClick handlers, not anchor hrefs (see
      // Navigation.tsx:199 handleConversationClick). The resilient marker
      // is that the conversations-container has at least one tile after
      // reload — the exact title is LLM-generated and not stable.
      await expect(
        page.locator('.conversations-container > div').first(),
      ).toBeVisible({ timeout: 15_000 });
    } finally {
      await context.close();
    }
  });

  test('save_conversation=false skips all four tables', async ({ browser }) => {
    const { sub, token } = await newUserContext(browser);

    // Sanity: the user has nothing yet.
    expect(
      await countRows('conversations', {
        sql: 'user_id = $1',
        params: [sub],
      }),
    ).toBe(0);

    const result = await streamDirect(token, {
      question: 'ephemeral probe — e2e-p2-07-no-save',
      history: '[]',
      save_conversation: false,
      isNoneDoc: true,
    });
    expect(result.status).toBe(200);
    // When save_conversation=false the route emits `{"type":"id","id":"None"}`
    // (stringified None) — no real UUID persisted.
    expect(result.conversationId).toBe('None');

    // Key invariant: conversations + conversation_messages must be empty
    // for this user. token_usage still fires (it's per-LLM-call, not per
    // conversation); user_logs also fires (audit log). We only assert on
    // the two "persistent chat state" tables.
    expect(
      await countRows('conversations', {
        sql: 'user_id = $1',
        params: [sub],
      }),
    ).toBe(0);

    const msgs = await fetchMessagesForUser(sub);
    expect(msgs).toHaveLength(0);
  });

  test('silent-break: two concurrent /stream calls on the same conversation_id — neither 500s and positions stay unique', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Seed a conversation with one completed turn. We need an existing
      // conversation_id before firing the concurrent pair, because the
      // append_message race only exists when the parent row is locked
      // under contention.
      const seed = await streamDirect(token, {
        question: 'seed turn — e2e-p2-07-race',
        history: '[]',
        save_conversation: true,
        isNoneDoc: true,
      });
      expect(seed.status).toBe(200);
      expect(seed.conversationId).toBeTruthy();
      const convId = seed.conversationId as string;

      // The seed conversation exists with exactly 1 message at position 0.
      {
        const msgs = await fetchMessagesForUser(sub);
        expect(msgs).toHaveLength(1);
        expect(msgs[0].position).toBe(0);
      }

      // Fire two /stream calls in parallel on the same conversation_id.
      // If the advisory SELECT ... FOR UPDATE lock is intact, they
      // serialize and land at positions 1 and 2. If the lock regresses,
      // both read MAX(position)=0 at the same instant and both try to
      // INSERT at position 1 — the unique index raises and one returns
      // 500 (or drops the turn silently depending on error handling).
      const [a, b] = await Promise.all([
        streamDirect(token, {
          question: 'concurrent-A — e2e-p2-07-race',
          conversation_id: convId,
          save_conversation: true,
          isNoneDoc: true,
        }),
        streamDirect(token, {
          question: 'concurrent-B — e2e-p2-07-race',
          conversation_id: convId,
          save_conversation: true,
          isNoneDoc: true,
        }),
      ]);

      // Invariant 1: neither stream returned 500. (Flask emits
      // `status=400` with a sanitized "Unknown error occurred" body on
      // unhandled exceptions — we guard against THAT shape too, since a
      // lost message hides behind either status.)
      expect(a.status).toBe(200);
      expect(b.status).toBe(200);
      expect(a.text).not.toMatch(/Unknown error occurred/);
      expect(b.text).not.toMatch(/Unknown error occurred/);

      // Invariant 2: both streams emitted an `{"type":"error", ...}`-free
      // body. A broken advisory lock shows up as the stream emitting
      // `error` AFTER the LLM completed but BEFORE save_conversation
      // acks — no 500 on the wire, but a lost message in the DB.
      expect(a.text).not.toMatch(/"type":\s*"error"/);
      expect(b.text).not.toMatch(/"type":\s*"error"/);

      // Invariant 3: the DB has all three turns at UNIQUE positions
      // within the same conversation_id.
      const messages = await fetchMessagesForUser(sub);
      expect(messages).toHaveLength(3);
      const positionsForConv = messages
        .filter((m) => m.conversation_id === convId)
        .map((m) => m.position)
        .sort((x, y) => x - y);
      expect(positionsForConv).toEqual([0, 1, 2]);

      // Positions must be a strict dense sequence (no gaps, no dupes) —
      // a duplicate position would have thrown before reaching here, and
      // a gap would mean one append silently lost the allocation.
      expect(new Set(positionsForConv).size).toBe(positionsForConv.length);

      // Every message row must have both prompt and response populated.
      // A half-written row (prompt but no response) would be the signature
      // of a partial save from a crashed stream.
      for (const m of messages) {
        expect(m.prompt).toBeTruthy();
        expect(m.response).toBeTruthy();
      }

      // Invariant 4: only ONE `conversations` row was created (the seed).
      // A regressed append path sometimes creates a second conversation
      // to "recover" from a failed insert — we don't want that.
      expect(
        await countRows('conversations', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(1);
    } finally {
      await api.dispose();
    }
  });

  test('reload rehydrates via /api/get_single_conversation with the expected message shape', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const first = await streamDirect(token, {
        question: 'rehydrate-probe-Q1 — e2e-p2-07-rehydrate',
        history: '[]',
        save_conversation: true,
        isNoneDoc: true,
      });
      expect(first.status).toBe(200);
      const convId = first.conversationId as string;
      expect(convId).toBeTruthy();

      // Second turn appends at position 1 — exercises the
      // `append_message` fast path with an existing conversation.
      const second = await streamDirect(token, {
        question: 'rehydrate-probe-Q2 — e2e-p2-07-rehydrate',
        conversation_id: convId,
        save_conversation: true,
        isNoneDoc: true,
      });
      expect(second.status).toBe(200);

      const res = await api.get(
        `/api/get_single_conversation?id=${encodeURIComponent(convId)}`,
      );
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        queries: Array<{
          prompt: string;
          response: string;
          thought: string | null;
          sources: unknown[];
          tool_calls: unknown[];
          timestamp?: string;
          model_id?: string | null;
        }>;
      };
      expect(Array.isArray(body.queries)).toBe(true);
      expect(body.queries).toHaveLength(2);
      expect(body.queries[0].prompt).toBe(
        'rehydrate-probe-Q1 — e2e-p2-07-rehydrate',
      );
      expect(body.queries[1].prompt).toBe(
        'rehydrate-probe-Q2 — e2e-p2-07-rehydrate',
      );
      // Shape invariants — these are the keys the Redux slice expects;
      // a missing field from the PG rehydrate path would silently break
      // the frontend without a server 500.
      for (const q of body.queries) {
        expect(typeof q.prompt).toBe('string');
        expect(typeof q.response).toBe('string');
        expect(Array.isArray(q.sources)).toBe(true);
        expect(Array.isArray(q.tool_calls)).toBe(true);
      }
    } finally {
      await api.dispose();
    }
  });

  test('stream aborted mid-response leaves no ghost row and reloads cleanly', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Start a stream and abort it before it completes. The stream
      // handler's `GeneratorExit` branch saves a PARTIAL response when
      // `response_full` is truthy, or nothing at all when the abort
      // lands before any LLM bytes were accumulated. Either way we must
      // not see a half-written row (prompt set, response NULL).
      const controller = new AbortController();
      const fetchPromise = fetch(`${API_URL}/stream`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question: 'aborted turn — e2e-p2-07-abort',
          history: '[]',
          save_conversation: true,
          isNoneDoc: true,
        }),
        signal: controller.signal,
      })
        .then(async (r) => {
          try {
            await r.text();
          } catch {
            // stream was torn down mid-read — expected
          }
        })
        .catch(() => {
          // AbortError — expected
        });

      // Abort almost immediately — before the response headers fully land.
      await new Promise((resolve) => setTimeout(resolve, 10));
      controller.abort();
      await fetchPromise;

      // Give the backend a beat to finish any GeneratorExit cleanup.
      await new Promise((resolve) => setTimeout(resolve, 500));

      const messages = await fetchMessagesForUser(sub);
      // Either zero messages (abort landed pre-LLM) OR one fully-written
      // message (abort landed post-LLM and the partial-save branch ran).
      // A half-written row — prompt set but response null — is the
      // forbidden state.
      for (const m of messages) {
        expect(m.prompt).toBeTruthy();
        // response MAY be an empty string if the abort fired before the
        // first token, but must not be null-and-prompt-set simultaneously.
        expect(m.response === null).toBe(false);
      }

      // Reload: the existing conversation list should still be fetchable
      // and return a well-formed 200 (even if empty).
      const listRes = await api.get('/api/get_conversations');
      expect(listRes.status()).toBe(200);
    } finally {
      await api.dispose();
    }
  });
});
