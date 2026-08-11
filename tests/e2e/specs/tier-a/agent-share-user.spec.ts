/**
 * P2-12 · Cross-user agent share.
 *
 * Writes to `users.agent_preferences.shared_with_me` (JSONB) and
 * `agents.shared_token` (CITEXT UNIQUE). Exercises the full cross-user
 * share lifecycle — A shares, B opens via token, B lists, B removes —
 * plus the migration-critical silent-break: stale-id cleanup on A's
 * unshare, which lives in the GET /api/shared_agents read path
 * (`SharedAgents.get` in application/api/user/agents/sharing.py).
 *
 * // Silent-break covered: shared_with_me stale-id cleanup on A's unshare
 *    — when A toggles `shared:false`, the agent's `shared_token` is set NULL
 *    and its `shared` flag flips to false, but B's
 *    `agent_preferences.shared_with_me` still contains the agent id. The
 *    next `GET /api/shared_agents` for B must filter out ids whose agents
 *    are no longer shared AND also call `remove_shared_bulk` to strip
 *    those stale ids from B's prefs. If the cleanup regresses, B sees a
 *    zombie entry that 404s on open (or, worse, reappears after every
 *    list refresh).
 *
 * API-driven for speed; the UI share toggle is an optional surface —
 * `frontend/src/agents/AgentCard.tsx` calls `PUT /api/share_agent` and
 * `frontend/src/agents/SharedAgent.tsx` calls `GET /api/shared_agent?token=`,
 * so hitting the endpoints directly is functionally equivalent.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { newUserContext } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

const API_URL = process.env.API_URL ?? 'http://127.0.0.1:7099';

interface AgentShareRow {
  id: string;
  user_id: string;
  shared: boolean;
  shared_token: string | null;
  shared_metadata: Record<string, unknown> | null;
}

interface AgentPreferences {
  pinned?: string[];
  shared_with_me?: string[];
}

interface UserPrefsRow {
  user_id: string;
  agent_preferences: AgentPreferences;
}

interface SharedAgentListItem {
  id: string;
  name: string;
  shared: boolean;
  shared_token: string;
}

/**
 * Multipart-capable Playwright APIRequestContext: same Bearer-token
 * plumbing as `authedRequest` but without the default
 * `Content-Type: application/json` header so `post({ multipart })` can
 * set its own boundary. Mirrors the helper in `agents.spec.ts`.
 */
async function multipartAuthedRequest(token: string): Promise<APIRequestContext> {
  return playwright.request.newContext({
    baseURL: API_URL,
    extraHTTPHeaders: {
      Authorization: `Bearer ${token}`,
    },
  });
}

/**
 * Create a draft classic agent owned by the context's user. The sharing
 * endpoints don't care about `status` — they key off `repo.get_any(id, user)`
 * — so a draft agent is the cheapest possible fixture.
 */
async function createDraftAgent(
  ctx: APIRequestContext,
  name: string,
): Promise<string> {
  const res = await ctx.post('/api/create_agent', {
    multipart: {
      name,
      status: 'draft',
      agent_type: 'classic',
      chunks: '2',
    },
  });
  expect(
    res.status(),
    `create_agent draft should be 201, got ${res.status()} ${await res.text()}`,
  ).toBe(201);
  const body = (await res.json()) as { id: string };
  expect(body.id).toBeTruthy();
  return body.id;
}

/**
 * Toggle an agent's share state via `PUT /api/share_agent`. Returns the
 * new `shared_token` on share (null on unshare — the server clears it).
 */
async function toggleShare(
  api: APIRequestContext,
  agentId: string,
  shared: boolean,
  username = 'e2e-user-a',
): Promise<string | null> {
  const res = await api.put('/api/share_agent', {
    data: { id: agentId, shared, username },
  });
  expect(
    res.status(),
    `share_agent (${shared ? 'on' : 'off'}) should be 200, got ${res.status()} ${await res.text()}`,
  ).toBe(200);
  const body = (await res.json()) as { success: boolean; shared_token: string | null };
  expect(body.success).toBe(true);
  return body.shared_token;
}

async function fetchAgent(agentId: string): Promise<AgentShareRow | null> {
  const { rows } = await pg.query<AgentShareRow>(
    `SELECT id::text AS id, user_id, shared, shared_token, shared_metadata
       FROM agents
      WHERE id = CAST($1 AS uuid)`,
    [agentId],
  );
  return rows[0] ?? null;
}

async function fetchSharedWithMe(userId: string): Promise<string[]> {
  const { rows } = await pg.query<UserPrefsRow>(
    'SELECT user_id, agent_preferences FROM users WHERE user_id = $1',
    [userId],
  );
  if (!rows[0]) return [];
  const prefs = rows[0].agent_preferences ?? {};
  return Array.isArray(prefs.shared_with_me) ? prefs.shared_with_me : [];
}

test.describe('tier-a · cross-user agent share', () => {
  test.beforeEach(async () => {
    await resetDb();
  });


  test('A shares an agent and B opens it via token — B.shared_with_me gains the id', async ({
    browser,
  }) => {
    const { context: ctxA, sub: subA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, sub: subB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'shared by A');

      const sharedToken = await toggleShare(apiA, agentId, true, 'user-a');
      expect(sharedToken).toBeTruthy();

      // agents row carries shared=true + the token + non-null metadata.
      const rowShared = await fetchAgent(agentId);
      expect(rowShared).not.toBeNull();
      expect(rowShared!.shared).toBe(true);
      expect(rowShared!.shared_token).toBe(sharedToken);
      expect(rowShared!.shared_metadata).not.toBeNull();
      // shared_metadata shape is `{shared_by, shared_at}` — see sharing.py:245.
      expect(rowShared!.shared_metadata).toMatchObject({ shared_by: 'user-a' });

      // B opens the token URL — the handler upserts B's user row and adds
      // the agent id to `shared_with_me`.
      const openRes = await apiB.get(
        `/api/shared_agent?token=${encodeURIComponent(sharedToken as string)}`,
      );
      expect(openRes.status()).toBe(200);
      const openBody = (await openRes.json()) as { id: string; name: string };
      expect(openBody.id).toBe(agentId);
      expect(openBody.name).toBe('shared by A');

      // DB: B's prefs contain the agent id; A's prefs are untouched (the
      // handler's user_id != owner_id guard skips adding to the owner).
      const bShared = await fetchSharedWithMe(subB);
      expect(bShared).toEqual([agentId]);

      const aShared = await fetchSharedWithMe(subA);
      expect(aShared).not.toContain(agentId);
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });

  test("B's shared list returns A's agent via GET /api/shared_agents", async ({
    browser,
  }) => {
    const { context: ctxA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'listed for B');
      const sharedToken = await toggleShare(apiA, agentId, true);
      // Seed B's prefs by opening the token URL once — this is the only
      // documented path that adds an id to `shared_with_me`.
      const openRes = await apiB.get(
        `/api/shared_agent?token=${encodeURIComponent(sharedToken as string)}`,
      );
      expect(openRes.status()).toBe(200);

      const listRes = await apiB.get('/api/shared_agents');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as SharedAgentListItem[];
      expect(list).toHaveLength(1);
      expect(list[0].id).toBe(agentId);
      expect(list[0].name).toBe('listed for B');
      expect(list[0].shared).toBe(true);
      expect(list[0].shared_token).toBe(sharedToken);
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });

  test("B removes shared agent — B's prefs clear but A's agent row is untouched", async ({
    browser,
  }) => {
    const { context: ctxA, sub: subA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, sub: subB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'B will remove me');
      const sharedToken = await toggleShare(apiA, agentId, true);
      const openRes = await apiB.get(
        `/api/shared_agent?token=${encodeURIComponent(sharedToken as string)}`,
      );
      expect(openRes.status()).toBe(200);
      expect(await fetchSharedWithMe(subB)).toEqual([agentId]);

      const removeRes = await apiB.delete(
        `/api/remove_shared_agent?id=${agentId}`,
      );
      expect(removeRes.status()).toBe(200);
      const removeBody = (await removeRes.json()) as {
        success: boolean;
        action: string;
      };
      expect(removeBody.success).toBe(true);
      expect(removeBody.action).toBe('removed');

      // B's `shared_with_me` is now empty; the agent itself is still shared
      // (shared=true, token intact) — remove_shared_agent only strips the
      // recipient's prefs, not the owner's share state.
      expect(await fetchSharedWithMe(subB)).toEqual([]);
      const agentRow = await fetchAgent(agentId);
      expect(agentRow!.shared).toBe(true);
      expect(agentRow!.shared_token).toBe(sharedToken);
      // A is the owner — A's prefs shouldn't have the id (owners never get
      // it added) and definitely shouldn't have changed.
      expect(await fetchSharedWithMe(subA)).not.toContain(agentId);
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('silent-break: A unshares — next GET /api/shared_agents for B strips the stale id', async ({
    browser,
  }) => {
    const { context: ctxA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, sub: subB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'about to be unshared');
      const sharedToken = await toggleShare(apiA, agentId, true);

      // B adds it to `shared_with_me` by opening the token URL.
      const openRes = await apiB.get(
        `/api/shared_agent?token=${encodeURIComponent(sharedToken as string)}`,
      );
      expect(openRes.status()).toBe(200);
      expect(await fetchSharedWithMe(subB)).toEqual([agentId]);

      // A unshares — the row stays (`shared=false`, `shared_token=NULL`)
      // but B's prefs are NOT touched by the unshare path. The stale id
      // lives in B's prefs until the list GET cleans it up.
      const unshareToken = await toggleShare(apiA, agentId, false);
      expect(unshareToken).toBeNull();

      const rowAfterUnshare = await fetchAgent(agentId);
      expect(rowAfterUnshare).not.toBeNull();
      expect(rowAfterUnshare!.shared).toBe(false);
      expect(rowAfterUnshare!.shared_token).toBeNull();

      // Pre-cleanup: B's prefs still contain the stale id. (If this
      // invariant flips one day — e.g. unshare proactively strips from
      // every user's prefs — delete this assertion; the test below is the
      // real invariant.)
      expect(await fetchSharedWithMe(subB)).toContain(agentId);

      // The cleanup path in SharedAgents.get:
      //   1. Returns an empty list (no agent matches `shared=true`).
      //   2. Calls `remove_shared_bulk` to strip the stale id from B's prefs.
      const listRes = await apiB.get('/api/shared_agents');
      expect(listRes.status()).toBe(200);
      const list = (await listRes.json()) as SharedAgentListItem[];
      expect(list).toEqual([]);

      // Post-cleanup: B's `shared_with_me` no longer contains the id.
      // If the cleanup is broken, B would see a zombie entry on the next
      // refresh that 404s on open.
      expect(await fetchSharedWithMe(subB)).not.toContain(agentId);
      expect(await fetchSharedWithMe(subB)).toEqual([]);
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('citext token lookup is case-insensitive — lowercase token still resolves', async ({
    browser,
  }) => {
    const { context: ctxA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, sub: subB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'citext lookup');
      const sharedToken = (await toggleShare(apiA, agentId, true)) as string;
      expect(sharedToken).toBeTruthy();

      // `secrets.token_urlsafe(32)` yields base64url chars (upper, lower,
      // digits, `-`, `_`) — the CITEXT UNIQUE column on `agents.shared_token`
      // makes lookups case-insensitive. Only run the lowercase variant if
      // it actually differs from the original; otherwise the assertion is
      // vacuous. We also verify against uppercase as a belt-and-suspenders.
      const lower = sharedToken.toLowerCase();
      const upper = sharedToken.toUpperCase();
      const variants = new Set<string>();
      if (lower !== sharedToken) variants.add(lower);
      if (upper !== sharedToken) variants.add(upper);
      // If token_urlsafe ever emitted a case-insensitive-identical string
      // (all digits/symbols) just skip — nothing to prove.
      test.skip(
        variants.size === 0,
        'shared_token has no case-sensitive chars; citext check is vacuous',
      );

      for (const variant of variants) {
        const res = await apiB.get(
          `/api/shared_agent?token=${encodeURIComponent(variant)}`,
        );
        expect(
          res.status(),
          `case-variant token (${variant}) should resolve via citext, got ${res.status()}`,
        ).toBe(200);
        const body = (await res.json()) as { id: string };
        expect(body.id).toBe(agentId);
      }

      // And B's prefs reflect the add (idempotent — append-if-not-present).
      expect(await fetchSharedWithMe(subB)).toEqual([agentId]);
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });

  test('shared-agent delete — trigger strips id from both pinned and shared_with_me for every user', async ({
    browser,
  }) => {
    const { context: ctxA, sub: subA, token: tokenA } = await newUserContext(browser);
    const { context: ctxB, sub: subB, token: tokenB } = await newUserContext(browser);
    const multiA = await multipartAuthedRequest(tokenA);
    const apiA = await authedRequest(playwright, tokenA);
    const apiB = await authedRequest(playwright, tokenB);
    try {
      const agentId = await createDraftAgent(multiA, 'doomed shared');
      const sharedToken = (await toggleShare(apiA, agentId, true)) as string;

      // B adds it to `shared_with_me` via the token open.
      const openRes = await apiB.get(
        `/api/shared_agent?token=${encodeURIComponent(sharedToken)}`,
      );
      expect(openRes.status()).toBe(200);

      // Seed A's `pinned` (owner pins their own agent) and B's `pinned`
      // (recipient pins the shared agent) directly — the trigger must
      // strip the id from BOTH users' pinned AND shared_with_me on delete.
      // The `/api/pin_agent` route does the same UPDATE via
      // UsersRepository.add_pinned; driving SQL here keeps this test
      // focused on the `cleanup_user_agent_prefs` trigger path.
      await pg.query(
        `UPDATE users
            SET agent_preferences = jsonb_set(
                  agent_preferences,
                  '{pinned}',
                  COALESCE(agent_preferences->'pinned', '[]'::jsonb) || to_jsonb($2::text)
                )
          WHERE user_id = $1`,
        [subA, agentId],
      );
      await pg.query(
        `UPDATE users
            SET agent_preferences = jsonb_set(
                  agent_preferences,
                  '{pinned}',
                  COALESCE(agent_preferences->'pinned', '[]'::jsonb) || to_jsonb($2::text)
                )
          WHERE user_id = $1`,
        [subB, agentId],
      );

      // Sanity: both users have the id somewhere in their prefs before delete.
      const { rows: beforeRows } = await pg.query<UserPrefsRow>(
        'SELECT user_id, agent_preferences FROM users WHERE user_id = ANY($1::text[])',
        [[subA, subB]],
      );
      expect(beforeRows).toHaveLength(2);
      for (const row of beforeRows) {
        const pinned = row.agent_preferences.pinned ?? [];
        const shared = row.agent_preferences.shared_with_me ?? [];
        expect(
          pinned.includes(agentId) || shared.includes(agentId),
          `user ${row.user_id} should have ${agentId} in pinned or shared_with_me pre-delete`,
        ).toBe(true);
      }

      // A hard-deletes the agent — `cleanup_user_agent_prefs` (BEFORE
      // DELETE on `agents`) scrubs the id from every users row's pinned
      // and shared_with_me arrays in a single UPDATE.
      const deleteRes = await multiA.delete(`/api/delete_agent?id=${agentId}`);
      expect(
        deleteRes.status(),
        `delete_agent should be 200, got ${deleteRes.status()} ${await deleteRes.text()}`,
      ).toBe(200);

      // Post-delete: the agents row is gone and both users' prefs have
      // been scrubbed of the id in both arrays.
      expect(await fetchAgent(agentId)).toBeNull();

      const { rows: afterRows } = await pg.query<UserPrefsRow>(
        'SELECT user_id, agent_preferences FROM users WHERE user_id = ANY($1::text[])',
        [[subA, subB]],
      );
      expect(afterRows).toHaveLength(2);
      for (const row of afterRows) {
        const pinned = row.agent_preferences.pinned ?? [];
        const shared = row.agent_preferences.shared_with_me ?? [];
        expect(
          pinned,
          `user ${row.user_id} pinned should not contain deleted agent`,
        ).not.toContain(agentId);
        expect(
          shared,
          `user ${row.user_id} shared_with_me should not contain deleted agent`,
        ).not.toContain(agentId);
      }
    } finally {
      await multiA.dispose();
      await apiA.dispose();
      await apiB.dispose();
      await ctxA.close();
      await ctxB.close();
    }
  });
});
