/**
 * Tier-B · conversation visibility (persist vs. sidebar display)
 *
 * Exercises the conversation-visibility contract end-to-end against the live
 * stack. Conversations always persist; visibility defaults to `hidden` for
 * EVERY request, and only an explicit request-level `visibility: "listed"` —
 * which the first-party UI sends on normal chats — lists a row in the sidebar
 * (resolve_persistence in
 * application/api/answer/services/persistence_policy.py). The legacy
 * `save_conversation` flag is deprecated and has no effect; whether a row
 * surfaces in GET /api/get_conversations is governed by the
 * `conversations.visibility` column ('listed' | 'hidden').
 *
 * Matrix covered:
 *   1. first-party /stream, visibility:'listed' (as the UI sends) → listed, in sidebar
 *   2. first-party /stream, visibility omitted                    → hidden, not in sidebar (but persisted)
 *   3. api-key agent /stream                                      → hidden by default; legacy
 *      save_conversation:true must NOT list; explicit visibility:'listed' does
 *   4. /v1/chat/completions (OpenAI-compat)                       → always hidden, even with
 *      docsgpt.save_conversation:true (the legacy flag external clients still send)
 *
 * Cases 3 and 4 are the regression guard for the sidebar-pollution bug where
 * API clients sending the legacy flag listed conversations into the agent
 * owner's sidebar.
 *
 * API-driven: assertions read the DB (`conversations.visibility`) and the real
 * sidebar endpoint, not stream internals.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { multipartAuthedRequest, publishClassicAgent } from '../../helpers/agents.js';
import { newUserContext } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { streamOnce } from '../../helpers/streaming.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Read the `visibility` column for a conversation id. */
async function visibilityOf(convId: string): Promise<string | null> {
  const { rows } = await pg.query<{ visibility: string }>(
    'SELECT visibility FROM conversations WHERE id = CAST($1 AS uuid)',
    [convId],
  );
  return rows[0]?.visibility ?? null;
}

/** The actual sidebar: GET /api/get_conversations returns only listed rows. */
async function sidebarIds(api: APIRequestContext): Promise<string[]> {
  const res = await api.get('/api/get_conversations');
  expect(res.ok(), `get_conversations ${res.status()}`).toBeTruthy();
  const list = (await res.json()) as Array<{ id: string }>;
  return list.map((c) => c.id);
}

/** Bearer context carrying a raw agent api_key (v1 auth shape). */
async function agentKeyRequest(key: string): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
    },
  });
}

test.describe('tier-b · conversation visibility', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('first-party chat (visibility: listed, as the UI sends) persists as listed and appears in the sidebar', async ({
    browser,
  }) => {
    const { context, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await streamOnce(api, {
        question: 'first-party listed turn',
        conversation_id: null,
        visibility: 'listed',
        isNoneDoc: true,
        chunks: '0',
      });
      expect(convId).toMatch(UUID_RE);
      expect(await visibilityOf(convId)).toBe('listed');
      expect(await sidebarIds(api)).toContain(convId);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('first-party chat without a visibility opt-in persists hidden and is excluded from the sidebar', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const convId = await streamOnce(api, {
        question: 'first-party hidden turn',
        conversation_id: null,
        isNoneDoc: true,
        chunks: '0',
      });
      // A real UUID is emitted now (not the legacy stringified "None").
      expect(convId).toMatch(UUID_RE);
      expect(await visibilityOf(convId)).toBe('hidden');
      // The row persisted...
      expect(
        await countRows('conversations', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(1);
      // ...but it never surfaces in the sidebar.
      expect(await sidebarIds(api)).not.toContain(convId);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('api-key agent chat hides by default; legacy save_conversation must not list, explicit visibility does', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { key } = await publishClassicAgent(api, multipart, sub, 'vis-agent');

      // api_key present, no flags → hidden by default.
      const hidden = await streamOnce(api, {
        question: 'agent default hidden',
        conversation_id: null,
        api_key: key,
        isNoneDoc: true,
        chunks: '0',
      });
      expect(await visibilityOf(hidden)).toBe('hidden');

      // Regression guard: the legacy flag — which external integrations
      // still send meaning "persist" — must NOT list into the owner's
      // sidebar.
      const legacy = await streamOnce(api, {
        question: 'agent legacy flag stays hidden',
        conversation_id: null,
        api_key: key,
        save_conversation: true,
        isNoneDoc: true,
        chunks: '0',
      });
      expect(await visibilityOf(legacy)).toBe('hidden');

      // Explicit opt-in → listed.
      const listed = await streamOnce(api, {
        question: 'agent opt-in listed',
        conversation_id: null,
        api_key: key,
        visibility: 'listed',
        isNoneDoc: true,
        chunks: '0',
      });
      expect(await visibilityOf(listed)).toBe('listed');

      // The owner's sidebar shows only the opted-in conversation.
      const ids = await sidebarIds(api);
      expect(ids).toContain(listed);
      expect(ids).not.toContain(hidden);
      expect(ids).not.toContain(legacy);
    } finally {
      await multipart.dispose();
      await api.dispose();
      await context.close();
    }
  });

  test('v1 chat completions always persist hidden — even with the legacy docsgpt.save_conversation flag', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { key } = await publishClassicAgent(api, multipart, sub, 'v1-vis-agent');
      const v1 = await agentKeyRequest(key);
      try {
        // Default: persisted, hidden — not in the owner's sidebar.
        const r1 = await v1.post('/v1/chat/completions', {
          data: {
            model: 'docsgpt',
            messages: [{ role: 'user', content: 'hi v1 default' }],
            stream: false,
          },
        });
        expect(r1.status(), await r1.text()).toBe(200);
        expect(
          await countRows('conversations', { sql: 'user_id = $1', params: [sub] }),
        ).toBe(1);
        expect(
          await countRows('conversations', {
            sql: "user_id = $1 AND visibility = 'listed'",
            params: [sub],
          }),
        ).toBe(0);
        expect(await sidebarIds(api)).toHaveLength(0);

        // Regression guard: the legacy docsgpt.save_conversation flag —
        // which external clients built on the old contract still send —
        // must NOT list the conversation into the agent owner's sidebar.
        const r2 = await v1.post('/v1/chat/completions', {
          data: {
            model: 'docsgpt',
            messages: [{ role: 'user', content: 'hi v1 legacy flag' }],
            stream: false,
            docsgpt: { save_conversation: true },
          },
        });
        expect(r2.status(), await r2.text()).toBe(200);
        expect(
          await countRows('conversations', { sql: 'user_id = $1', params: [sub] }),
        ).toBe(2);
        expect(
          await countRows('conversations', {
            sql: "user_id = $1 AND visibility = 'listed'",
            params: [sub],
          }),
        ).toBe(0);
        // The owner's sidebar stays empty no matter what v1 clients send.
        expect(await sidebarIds(api)).toHaveLength(0);
      } finally {
        await v1.dispose();
      }
    } finally {
      await multipart.dispose();
      await api.dispose();
      await context.close();
    }
  });
});
