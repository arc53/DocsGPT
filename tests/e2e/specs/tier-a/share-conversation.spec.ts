/**
 * Phase 2 — P2-09 · Conversation share (non-promptable + promptable).
 *
 * Writes to the Tier-1 `shared_conversations` table on every share, and
 * additionally writes an `agents` row keyed on (prompt_id, chunks, source,
 * retriever) for promptable shares. The promptable path links back to
 * `prompts.id` via `agents.prompt_id` — this is the Mongo-ObjectId ->
 * PG-UUID translation seam where a silent break can lurk.
 *
 * // Silent-break covered: promptable share uses the real user prompt, not default fallback.
 *    If `_resolve_prompt_pg_id` in application/api/user/sharing/routes.py
 *    returns None for a valid, user-owned prompt (e.g. because the UUID
 *    branch is skipped and the legacy_mongo_id branch is consulted with
 *    the wrong id shape), `agents.prompt_id` silently lands as NULL, the
 *    shared agent falls back to the built-in default persona, and the
 *    visitor never knows. We pin this down with a DB-level assertion that
 *    `agents.prompt_id` equals the exact UUID we created for the user.
 */

// Silent-break covered: promptable share uses the real user prompt, not default fallback

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext, Browser, BrowserContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

interface AnswerResponse {
  conversation_id: string;
  answer: string;
  sources: unknown[];
  tool_calls: unknown[];
  thought: string;
}

interface ShareResponse {
  success: boolean;
  identifier: string;
}

interface SharedConversationRow {
  id: string;
  conversation_id: string;
  user_id: string;
  is_promptable: boolean;
  uuid: string;
  first_n_queries: number;
  api_key: string | null;
  prompt_id: string | null;
  chunks: number | null;
}

interface AgentRow {
  id: string;
  user_id: string;
  key: string | null;
  prompt_id: string | null;
  chunks: number | null;
  source_id: string | null;
  retriever: string | null;
  status: string;
}

/**
 * Seed a conversation by driving `/api/answer` once. That endpoint consumes
 * the same stream as `/api/stream` internally and returns a structured JSON
 * envelope, so we avoid hand-rolling an SSE parser. A single question
 * produces exactly one persisted message, which is what `first_n_queries`
 * on `shared_conversations` is counted from.
 */
async function seedConversation(
  api: APIRequestContext,
  question: string,
): Promise<string> {
  // NOTE: do NOT pass `history: []` — an empty-array history 500s
  // /api/answer (and 400s /stream). Omit it for fresh conversations.
  const res = await api.post('/api/answer', {
    data: { question, prompt_id: 'default' },
  });
  expect(res.status()).toBe(200);
  const body = (await res.json()) as AnswerResponse;
  expect(body.conversation_id).toBeTruthy();
  return body.conversation_id;
}

/**
 * POST /api/share with the `isPromptable` query string flag. Returns the
 * identifier UUID that the public viewer route keys on.
 */
async function shareConversation(
  api: APIRequestContext,
  conversationId: string,
  opts: {
    isPromptable: boolean;
    promptId?: string;
    chunks?: number;
    source?: string;
    retriever?: string;
  },
): Promise<{ identifier: string; status: number }> {
  const data: Record<string, unknown> = { conversation_id: conversationId };
  if (opts.promptId !== undefined) data.prompt_id = opts.promptId;
  if (opts.chunks !== undefined) data.chunks = opts.chunks;
  if (opts.source !== undefined) data.source = opts.source;
  if (opts.retriever !== undefined) data.retriever = opts.retriever;
  const res = await api.post(
    `/api/share?isPromptable=${opts.isPromptable ? 'true' : 'false'}`,
    { data },
  );
  const status = res.status();
  expect(status).toBeGreaterThanOrEqual(200);
  expect(status).toBeLessThan(300);
  const body = (await res.json()) as ShareResponse;
  expect(body.success).toBe(true);
  expect(body.identifier).toBeTruthy();
  return { identifier: body.identifier, status };
}

async function fetchSharedConversationRow(
  identifier: string,
): Promise<SharedConversationRow | null> {
  const { rows } = await pg.query<SharedConversationRow>(
    `SELECT id::text AS id, conversation_id::text AS conversation_id,
            user_id, is_promptable, uuid::text AS uuid, first_n_queries,
            api_key, prompt_id::text AS prompt_id, chunks
     FROM shared_conversations WHERE uuid = CAST($1 AS uuid)`,
    [identifier],
  );
  return rows[0] ?? null;
}

async function fetchAgentRowByKey(apiKey: string): Promise<AgentRow | null> {
  const { rows } = await pg.query<AgentRow>(
    `SELECT id::text AS id, user_id, key, prompt_id::text AS prompt_id,
            chunks, source_id::text AS source_id, retriever, status
     FROM agents WHERE key = $1`,
    [apiKey],
  );
  return rows[0] ?? null;
}

/**
 * Unauthenticated incognito visitor — a fresh BrowserContext with NO auth
 * token injected. This is exactly how a stranger following a share URL in
 * a new private window reaches the public `/share/:identifier` viewer.
 */
async function newIncognitoContext(browser: Browser): Promise<BrowserContext> {
  return browser.newContext();
}

test.describe('tier-a · conversation share', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('non-promptable share: public URL renders the first messages without auth', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    let visitorContext: BrowserContext | null = null;
    try {
      const question = 'What is the meaning of life?';
      const conversationId = await seedConversation(api, question);

      const { identifier, status } = await shareConversation(api, conversationId, {
        isPromptable: false,
      });
      expect(status).toBe(201);

      // DB assertion: exactly one row in shared_conversations, tied to our
      // sharer, not promptable, no agent key, first_n_queries >= 1.
      const row = await fetchSharedConversationRow(identifier);
      expect(row).not.toBeNull();
      expect(row?.user_id).toBe(sub);
      expect(row?.is_promptable).toBe(false);
      expect(row?.api_key).toBeNull();
      expect(row?.prompt_id).toBeNull();
      expect(row?.first_n_queries).toBeGreaterThanOrEqual(1);

      // Non-promptable path never mints an agents row.
      expect(await countRows('agents', { sql: 'user_id = $1', params: [sub] })).toBe(0);

      // Public viewer: open in an unauthenticated incognito context, no
      // token in localStorage, no Authorization header — it must still
      // return the shared payload. We hit the JSON endpoint directly
      // because the React viewer shells out to it and its success is the
      // load-bearing check; rendering is incidental.
      visitorContext = await newIncognitoContext(browser);
      const visitorRes = await visitorContext.request.get(
        `http://127.0.0.1:7099/api/shared_conversation/${identifier}`,
      );
      expect(visitorRes.status()).toBe(200);
      const visitorBody = (await visitorRes.json()) as {
        success: boolean;
        queries: Array<{ prompt: string; response: string | null }>;
        api_key?: string;
      };
      expect(visitorBody.success).toBe(true);
      expect(visitorBody.queries.length).toBeGreaterThanOrEqual(1);
      expect(visitorBody.queries[0].prompt).toBe(question);
      // Non-promptable shares must NOT leak an agent api_key downstream.
      expect(visitorBody.api_key).toBeUndefined();
    } finally {
      await api.dispose();
      if (visitorContext) await visitorContext.close();
      await context.close();
    }
  });

  test('promptable share with default prompt: agent row created with prompt_id NULL', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    let visitorContext: BrowserContext | null = null;
    try {
      const conversationId = await seedConversation(
        api,
        'Promptable default share question.',
      );

      // No prompt_id in the body — routes.py defaults it to "default",
      // which `_resolve_prompt_pg_id` returns None for. The agent row must
      // land with prompt_id IS NULL (built-in persona fallback, which is
      // correct for the default sentinel).
      const { identifier } = await shareConversation(api, conversationId, {
        isPromptable: true,
        chunks: 2,
      });

      const shared = await fetchSharedConversationRow(identifier);
      expect(shared).not.toBeNull();
      expect(shared?.is_promptable).toBe(true);
      expect(shared?.api_key).toBeTruthy();
      expect(shared?.prompt_id).toBeNull();
      expect(shared?.chunks).toBe(2);

      // Exactly one agents row for this user, keyed by the share's api_key,
      // with prompt_id NULL and chunks 2.
      expect(await countRows('agents', { sql: 'user_id = $1', params: [sub] })).toBe(1);
      const agent = await fetchAgentRowByKey(shared!.api_key!);
      expect(agent).not.toBeNull();
      expect(agent?.user_id).toBe(sub);
      expect(agent?.prompt_id).toBeNull();
      expect(agent?.chunks).toBe(2);
      expect(agent?.status).toBe('published');

      // Incognito visitor sees the api_key in the payload (promptable
      // shares expose it so the viewer UI can submit follow-ups).
      visitorContext = await newIncognitoContext(browser);
      const visitorRes = await visitorContext.request.get(
        `http://127.0.0.1:7099/api/shared_conversation/${identifier}`,
      );
      expect(visitorRes.status()).toBe(200);
      const visitorBody = (await visitorRes.json()) as {
        success: boolean;
        api_key?: string;
      };
      expect(visitorBody.success).toBe(true);
      expect(visitorBody.api_key).toBe(shared!.api_key);
    } finally {
      await api.dispose();
      if (visitorContext) await visitorContext.close();
      await context.close();
    }
  });

  test('silent-break: promptable share with a user prompt resolves prompt_id to the real UUID', async ({
    browser,
  }) => {
    // This is the migration-critical case. The prompt_id we send is a real
    // PG UUID (via /api/create_prompt). If `_resolve_prompt_pg_id` regresses
    // and skips the UUID path, the agent row lands with prompt_id NULL and
    // the shared visitor gets the built-in default persona — silently.
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    let visitorContext: BrowserContext | null = null;
    try {
      // 1. Create a distinctive user prompt via API.
      const promptCreate = await api.post('/api/create_prompt', {
        data: {
          name: 'e2e-share-allcaps',
          content:
            'You are an assistant who ALWAYS responds in ALL CAPITAL LETTERS, '
              + 'no matter how the user phrases their question.',
        },
      });
      expect(promptCreate.status()).toBe(200);
      const { id: promptId } = (await promptCreate.json()) as { id: string };
      // Sanity: the returned id is a UUID, not a legacy Mongo ObjectId.
      expect(promptId).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );

      // 2. Seed a conversation and share it promptably with the user prompt.
      const conversationId = await seedConversation(
        api,
        'Silent-break question — does prompt_id propagate?',
      );
      const { identifier } = await shareConversation(api, conversationId, {
        isPromptable: true,
        promptId,
        chunks: 2,
      });

      // 3. shared_conversations row links the prompt.
      const shared = await fetchSharedConversationRow(identifier);
      expect(shared).not.toBeNull();
      expect(shared?.is_promptable).toBe(true);
      expect(shared?.prompt_id).toBe(promptId);
      expect(shared?.chunks).toBe(2);
      expect(shared?.api_key).toBeTruthy();

      // 4. THE assertion: agents.prompt_id is NOT NULL AND equals the UUID
      // we created. Anything else (NULL, or a different UUID) means the
      // resolve helper silently fell back to default.
      const agent = await fetchAgentRowByKey(shared!.api_key!);
      expect(agent).not.toBeNull();
      expect(agent?.user_id).toBe(sub);
      expect(agent?.prompt_id).not.toBeNull();
      expect(agent?.prompt_id).toBe(promptId);

      // 5. Cross-check via FK: agents.prompt_id really points at OUR prompt
      // row, not some other user's — proves the user_id scoping in
      // `_resolve_prompt_pg_id` held up.
      const { rows: linked } = await pg.query<{ id: string; user_id: string; name: string }>(
        `SELECT p.id::text AS id, p.user_id, p.name
         FROM agents a JOIN prompts p ON p.id = a.prompt_id
         WHERE a.key = $1`,
        [shared!.api_key],
      );
      expect(linked).toHaveLength(1);
      expect(linked[0].id).toBe(promptId);
      expect(linked[0].user_id).toBe(sub);
      expect(linked[0].name).toBe('e2e-share-allcaps');

      // 6. Public visitor can load the shared payload (incognito) and gets
      // the same api_key pointing at the agent wired with our prompt. The
      // mock LLM is deterministic so the *text* of the response is hashed
      // on (model, messages, tool_choice) — we can't reliably assert
      // "response is ALL CAPS" without a fixture, but we CAN assert that
      // the visitor's api_key matches the agent whose prompt_id is our
      // UUID. That closes the silent-break loop end-to-end.
      visitorContext = await newIncognitoContext(browser);
      const visitorRes = await visitorContext.request.get(
        `http://127.0.0.1:7099/api/shared_conversation/${identifier}`,
      );
      expect(visitorRes.status()).toBe(200);
      const visitorBody = (await visitorRes.json()) as {
        success: boolean;
        api_key?: string;
      };
      expect(visitorBody.success).toBe(true);
      expect(visitorBody.api_key).toBe(shared!.api_key);
    } finally {
      await api.dispose();
      if (visitorContext) await visitorContext.close();
      await context.close();
    }
  });

  test('re-sharing promptably with identical params reuses the agent key', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const promptCreate = await api.post('/api/create_prompt', {
        data: { name: 'e2e-share-reuse', content: 'Reuse-check prompt.' },
      });
      expect(promptCreate.status()).toBe(200);
      const { id: promptId } = (await promptCreate.json()) as { id: string };

      const conversationId = await seedConversation(api, 'Reuse question one.');

      const first = await shareConversation(api, conversationId, {
        isPromptable: true,
        promptId,
        chunks: 2,
      });
      // First share mints a new agent (201).
      expect(first.status).toBe(201);

      const second = await shareConversation(api, conversationId, {
        isPromptable: true,
        promptId,
        chunks: 2,
      });
      // Second share reuses the existing agent (200, not 201).
      expect(second.status).toBe(200);

      const firstShared = await fetchSharedConversationRow(first.identifier);
      const secondShared = await fetchSharedConversationRow(second.identifier);
      expect(firstShared).not.toBeNull();
      expect(secondShared).not.toBeNull();
      // The share-identifier dedup index means identical params hit the
      // same shared_conversations row — confirm that invariant too.
      expect(firstShared!.uuid).toBe(secondShared!.uuid);
      expect(firstShared!.api_key).toBe(secondShared!.api_key);

      // THE assertion for this test: exactly ONE agents row despite two
      // share calls. Drift would show up as two rows with distinct keys.
      expect(await countRows('agents', { sql: 'user_id = $1', params: [sub] })).toBe(1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('re-sharing promptably with different chunks mints a new agent row', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const promptCreate = await api.post('/api/create_prompt', {
        data: { name: 'e2e-share-chunks', content: 'Chunks-vary prompt.' },
      });
      expect(promptCreate.status()).toBe(200);
      const { id: promptId } = (await promptCreate.json()) as { id: string };

      const conversationId = await seedConversation(api, 'Chunks question.');

      const twoChunk = await shareConversation(api, conversationId, {
        isPromptable: true,
        promptId,
        chunks: 2,
      });
      expect(twoChunk.status).toBe(201);

      const fourChunk = await shareConversation(api, conversationId, {
        isPromptable: true,
        promptId,
        chunks: 4,
      });
      // Different chunks ⇒ `_find_reusable_share_agent` finds nothing ⇒
      // a brand-new agents row with a brand-new key is minted (201).
      expect(fourChunk.status).toBe(201);

      const twoRow = await fetchSharedConversationRow(twoChunk.identifier);
      const fourRow = await fetchSharedConversationRow(fourChunk.identifier);
      expect(twoRow).not.toBeNull();
      expect(fourRow).not.toBeNull();
      expect(twoRow!.api_key).not.toBe(fourRow!.api_key);
      expect(twoRow!.chunks).toBe(2);
      expect(fourRow!.chunks).toBe(4);

      // Two distinct agents rows now exist for this user, one per chunks
      // value, each wired to the same user prompt.
      expect(await countRows('agents', { sql: 'user_id = $1', params: [sub] })).toBe(2);

      const twoAgent = await fetchAgentRowByKey(twoRow!.api_key!);
      const fourAgent = await fetchAgentRowByKey(fourRow!.api_key!);
      expect(twoAgent?.chunks).toBe(2);
      expect(fourAgent?.chunks).toBe(4);
      expect(twoAgent?.prompt_id).toBe(promptId);
      expect(fourAgent?.prompt_id).toBe(promptId);
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
