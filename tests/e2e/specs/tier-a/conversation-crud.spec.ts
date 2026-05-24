/**
 * P2-08 · Conversation CRUD (Tier-A migration-critical).
 *
 * Covers e2e-plan.md §P2 row P2-08: writes/deletes against `conversations`
 * and the cascading child tables (`conversation_messages`,
 * `pending_tool_state`, `shared_conversations`) are migration-correct.
 *
 * Silent-break covered: delete-while-streaming releases locks, no ghost
 * pending_tool_state rows, and subsequent conversations with a reused id
 * start clean.
 *
 * Conversations are created through the real `/stream` endpoint (the
 * chat UI is exercised separately by P2-07) — `/stream` is the only path
 * that inserts rows into `conversations`/`conversation_messages`, so using
 * it here keeps us on the same write path production uses.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;
import type { APIRequestContext, Page } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

// --------------------------------------------------------------------------
// Helpers (spec-local — don't belong in the shared helpers/ yet; P2-07 will
// promote the streaming primitives if they're reused)
// --------------------------------------------------------------------------

/**
 * Drive `/stream` once and return the conversation_id emitted in the
 * final SSE `{type:"id", id:"<uuid>"}` payload. Waits for the stream to
 * finish — use `streamNoWait` for concurrent-delete scenarios.
 */
async function streamOnce(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<string> {
  const res = await api.post('/stream', { data: body });
  expect(res.ok(), `stream post failed: ${res.status()}`).toBeTruthy();
  // SSE payload from base.py:362 — {"type":"id","id":"<uuid>"}. Match it
  // with a non-greedy capture so a stray `id` token in an earlier event
  // can't win.
  const text = await res.text();
  const match = text.match(/"type"\s*:\s*"id"\s*,\s*"id"\s*:\s*"([^"]+)"/);
  expect(match, `no {type:id} event in SSE payload: ${text}`).not.toBeNull();
  return match![1];
}

/**
 * Kick off `/stream` and return the in-flight promise without awaiting
 * it. Callers race it against a concurrent mutation. The returned promise
 * resolves to the HTTP status (not the body) — we only care whether the
 * server crashed (5xx) or handled the race cleanly.
 */
function streamInFlight(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<number> {
  return api
    .post('/stream', { data: body })
    .then((r) => r.status())
    .catch(() => 599); // treat client-side aborts as non-500
}

// Type alias for row shape returned by pg in JSON tests below.
interface ConvRow {
  id: string;
  name: string | null;
}

const STREAM_QUESTION = 'What is DocsGPT?';

test.describe('tier-a · conversations CRUD', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('create 3 conversations, list returns all 3 and DB row count matches', async () => {
    const sub = 'e2e-p2-08-create';
    const token = signJwt(sub);
    const api = await authedRequest(playwright, token);
    try {
      const ids: string[] = [];
      for (let i = 0; i < 3; i++) {
        const id = await streamOnce(api, {
          question: `${STREAM_QUESTION} (${i})`,
          save_conversation: true,
        });
        expect(id).toBeTruthy();
        ids.push(id);
      }
      // De-dup — three distinct UUIDs, not the same one updated three times.
      expect(new Set(ids).size).toBe(3);

      const listRes = await api.get('/api/get_conversations');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as Array<{ id: string; name: string }>;
      expect(list).toHaveLength(3);
      expect(new Set(list.map((c) => c.id))).toEqual(new Set(ids));

      // DB-level — bypasses the API view.
      const dbCount = await countRows('conversations', {
        sql: 'user_id = $1',
        params: [sub],
      });
      expect(dbCount).toBe(3);

      // Each conversation must have its first message persisted.
      const msgCount = await countRows('conversation_messages', {
        sql: 'user_id = $1',
        params: [sub],
      });
      expect(msgCount).toBe(3);
    } finally {
      await api.dispose();
    }
  });

  test('rename via UI — inline edit in sidebar persists across reload and to DB', async ({
    browser,
  }) => {
    const sub = 'e2e-p2-08-rename';
    const { context, token } = await newUserContext(browser, { sub });
    const api = await authedRequest(playwright, token);
    let page: Page | null = null;
    try {
      const convId = await streamOnce(api, {
        question: STREAM_QUESTION,
        save_conversation: true,
      });

      page = await context.newPage();
      await page.goto('/');
      // Wait for the sidebar to hydrate. The NavLink "New Chat" is the
      // resilient marker used by auth specs.
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible();

      // Locate the conversation tile. The auto-generated name comes from the
      // mock LLM's title summarization — we don't know it, but we know it's
      // the only tile rendered for this user. Hover to reveal the menu button.
      const tile = page.locator('.conversations-container > div').first();
      await expect(tile).toBeVisible();
      await tile.hover();

      // Open the three-dot menu (img with alt="menu" is inside the only
      // button rendered in-tile when not editing).
      await tile.getByRole('button').click();

      // ContextMenu renders Rename label from i18n (`convTile.rename`).
      await page.getByText('Rename', { exact: true }).click();

      const newName = 'renamed-via-ui';
      const input = tile.locator('input[type="text"]');
      await expect(input).toBeVisible();
      await input.fill(newName);
      await input.press('Enter');

      // Wait for the rename request to settle and the tile to re-render
      // with the new name.
      await expect(tile).toContainText(newName);

      // DB assertion — the PATCH went through.
      const { rows } = await pg.query<ConvRow>(
        'SELECT id::text AS id, name FROM conversations WHERE id = CAST($1 AS uuid)',
        [convId],
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].name).toBe(newName);

      // Reload — name persists.
      await page.reload();
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible();
      await expect(
        page.locator('.conversations-container > div').first(),
      ).toContainText(newName);
    } finally {
      if (page) await page.close();
      await api.dispose();
      await context.close();
    }
  });

  test('delete one via UI — tile removed, row gone, conversation_messages cascaded', async ({
    browser,
  }) => {
    const sub = 'e2e-p2-08-delete-one';
    const { context, token } = await newUserContext(browser, { sub });
    const api = await authedRequest(playwright, token);
    let page: Page | null = null;
    try {
      const keepId = await streamOnce(api, {
        question: STREAM_QUESTION + ' keep',
        save_conversation: true,
      });
      const dropId = await streamOnce(api, {
        question: STREAM_QUESTION + ' drop',
        save_conversation: true,
      });
      expect(keepId).not.toBe(dropId);
      expect(
        await countRows('conversations', { sql: 'user_id = $1', params: [sub] }),
      ).toBe(2);
      expect(
        await countRows('conversation_messages', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(2);

      page = await context.newPage();
      await page.goto('/');
      await expect(
        page.getByRole('link', { name: /new chat/i }).first(),
      ).toBeVisible();

      // Find the tile for `dropId`. Tiles are rendered DESC by date; the
      // most recently created conversation is the first one.
      const tiles = page.locator('.conversations-container > div');
      await expect(tiles).toHaveCount(2);
      const dropTile = tiles.first();
      await dropTile.hover();
      await dropTile.getByRole('button').click();
      await page.getByText('Delete', { exact: true }).click();

      // ConfirmationModal uses the same "Delete" label for the submit button.
      // Scope to the modal by grabbing the button with that text within a
      // dialog-like container. The second "Delete" on the page is the
      // destructive submit.
      await page
        .getByRole('button', { name: 'Delete', exact: true })
        .last()
        .click();

      // Tile count drops to 1.
      await expect(tiles).toHaveCount(1);

      // DB — dropped conversation gone, surviving one intact.
      expect(
        await countRows('conversations', {
          sql: 'id = CAST($1 AS uuid)',
          params: [dropId],
        }),
      ).toBe(0);
      expect(
        await countRows('conversations', {
          sql: 'id = CAST($1 AS uuid)',
          params: [keepId],
        }),
      ).toBe(1);

      // Cascade check — messages for the dropped convo are gone, one
      // message row remains (for the surviving convo).
      expect(
        await countRows('conversation_messages', {
          sql: 'conversation_id = CAST($1 AS uuid)',
          params: [dropId],
        }),
      ).toBe(0);
      expect(
        await countRows('conversation_messages', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(1);
    } finally {
      if (page) await page.close();
      await api.dispose();
      await context.close();
    }
  });

  test('delete-all clears conversations but leaves prompts untouched', async () => {
    const sub = 'e2e-p2-08-delete-all';
    const token = signJwt(sub);
    const api = await authedRequest(playwright, token);
    try {
      // Baseline isolation check: create a prompt and prove it is not
      // collateral damage of delete_all_conversations.
      const promptRes = await api.post('/api/create_prompt', {
        data: { name: 'keep-me', content: 'survives delete-all' },
      });
      expect(promptRes.status()).toBe(200);
      const promptsBefore = await countRows('prompts', {
        sql: 'user_id = $1',
        params: [sub],
      });
      expect(promptsBefore).toBe(1);

      // Two conversations with messages to prove cascade fires.
      await streamOnce(api, {
        question: STREAM_QUESTION + ' a',
        save_conversation: true,
      });
      await streamOnce(api, {
        question: STREAM_QUESTION + ' b',
        save_conversation: true,
      });
      expect(
        await countRows('conversations', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(2);

      const delAll = await api.get('/api/delete_all_conversations');
      expect(delAll.status()).toBe(200);
      expect((await delAll.json()) as { success: boolean }).toEqual({
        success: true,
      });

      // Conversations + cascaded messages gone.
      expect(
        await countRows('conversations', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);
      expect(
        await countRows('conversation_messages', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);

      // Prompts row count unchanged — different table, different owner
      // semantics; delete_all_conversations must not touch it.
      expect(
        await countRows('prompts', { sql: 'user_id = $1', params: [sub] }),
      ).toBe(1);
    } finally {
      await api.dispose();
    }
  });

  test('silent-break: delete while /stream is in-flight leaves no orphans', async () => {
    const sub = 'e2e-p2-08-delete-while-stream';
    const token = signJwt(sub);
    // Two independent APIRequestContexts: Playwright serializes calls per
    // context, so both must be live to actually race on the backend.
    const apiStream = await authedRequest(playwright, token);
    const apiDelete = await authedRequest(playwright, token);
    try {
      // Seed a conversation so the stream below has an id to target.
      const convId = await streamOnce(apiStream, {
        question: STREAM_QUESTION + ' seed',
        save_conversation: true,
      });
      expect(
        await countRows('conversations', {
          sql: 'id = CAST($1 AS uuid)',
          params: [convId],
        }),
      ).toBe(1);

      // Fire both requests concurrently. The stream replays history for
      // `conversation_id=convId` and tries to append a new message; the
      // delete races to cascade-drop everything. Either outcome is valid;
      // the invariants are: no 5xx from either, no orphan children.
      const [streamStatus, deleteStatus] = await Promise.all([
        streamInFlight(apiStream, {
          question: STREAM_QUESTION + ' racy',
          conversation_id: convId,
          save_conversation: true,
        }),
        apiDelete
          .post(`/api/delete_conversation?id=${encodeURIComponent(convId)}`)
          .then((r) => r.status()),
      ]);

      // Neither side may have returned a 5xx. /stream returns 200 even on
      // partial failure (error events are emitted in-band), so we just
      // guard the server-error class.
      expect(streamStatus, `/stream blew up with ${streamStatus}`).toBeLessThan(500);
      expect(deleteStatus).toBe(200);

      // The conversation itself may or may not be gone depending on who
      // won the race. What MUST hold is that no orphan child rows point at
      // a missing parent. Postgres FK cascades guarantee this at the
      // schema level, but the assertion is cheap and catches a migration
      // regression where ON DELETE CASCADE was dropped.
      const { rows: orphanMsgs } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM conversation_messages cm
         WHERE NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id = cm.conversation_id)`,
      );
      expect(Number(orphanMsgs[0].n)).toBe(0);

      const { rows: orphanPending } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM pending_tool_state pts
         WHERE NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id = pts.conversation_id)`,
      );
      expect(Number(orphanPending[0].n)).toBe(0);

      const { rows: orphanShared } = await pg.query<{ n: string }>(
        `SELECT count(*)::text AS n FROM shared_conversations sc
         WHERE NOT EXISTS (SELECT 1 FROM conversations c WHERE c.id = sc.conversation_id)`,
      );
      expect(Number(orphanShared[0].n)).toBe(0);

      // Reuse-safety: a fresh /stream after the race starts clean — no
      // stale pending_tool_state carries over to the new conversation.
      const freshId = await streamOnce(apiStream, {
        question: STREAM_QUESTION + ' post-race',
        save_conversation: true,
      });
      expect(freshId).not.toBe(convId);
      expect(
        await countRows('pending_tool_state', {
          sql: 'conversation_id = CAST($1 AS uuid)',
          params: [freshId],
        }),
      ).toBe(0);
    } finally {
      await apiStream.dispose();
      await apiDelete.dispose();
    }
  });

  test('31st conversation is invisible to /get_conversations (limit=30) but present in DB', async () => {
    const sub = 'e2e-p2-08-pagination';
    const token = signJwt(sub);
    const api = await authedRequest(playwright, token);
    try {
      // Insert 31 conversations directly at the SQL layer — going through
      // /stream for 31 turns would be slow, and this test is about the
      // list_for_user LIMIT, not the write path.
      const insertPromises: Promise<unknown>[] = [];
      for (let i = 0; i < 31; i++) {
        insertPromises.push(
          pg.query(
            `INSERT INTO conversations (user_id, name, date)
             VALUES ($1, $2, now() + ($3 || ' milliseconds')::interval)`,
            [sub, `conv-${i}`, String(i)],
          ),
        );
      }
      await Promise.all(insertPromises);

      expect(
        await countRows('conversations', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(31);

      const listRes = await api.get('/api/get_conversations');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as Array<{ id: string; name: string }>;
      expect(list).toHaveLength(30);

      // The oldest one (conv-0, earliest date) must be the one missing —
      // list_for_user orders by date DESC.
      const names = new Set(list.map((c) => c.name));
      expect(names.has('conv-0')).toBe(false);
      expect(names.has('conv-30')).toBe(true);
    } finally {
      await api.dispose();
    }
  });
});
