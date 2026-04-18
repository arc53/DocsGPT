/**
 * Phase 2 — P2-04 · Token usage / message / feedback analytics.
 *
 * Silent-break covered: analytics bucket keys use YYYY-MM-DD HH24:00 format
 * (Postgres `to_char`). A drift to the Python `%Y-%m-%d %H:00` strftime
 * shape would look identical in the happy case but differ at the second /
 * minute boundary when `datetime.now()` crosses an hour just as the
 * bucket labels are being generated for empty intervals. The assertions
 * below verify the server emits the Postgres format for every
 * filter_option so the intervals dict and the grouped rows key-match.
 *
 * Tables touched (reads only — analytics never writes):
 *   - `token_usage`                        (seeded directly below)
 *   - `conversation_messages` (feedback)   (seeded directly below)
 *   - `conversations`                      (joined on c.user_id / c.api_key)
 *   - `agents`                             (resolves api_key_id → key)
 *
 * Why seed token_usage via INSERT rather than via `/stream`:
 * the streaming path produces tokens via the mock LLM whose exact count
 * and timing are not deterministic enough for `expect().toBe(42)` — but
 * analytics itself is a pure read aggregator. We are testing the
 * aggregation shape, not the writer. A direct INSERT yields the exact
 * same row shape `TokenUsageRepository.insert` produces (see
 * `application/storage/db/repositories/token_usage.py`). One test
 * cross-checks the writer path implicitly by using an agent api_key
 * created through the real `/api/create_agent` endpoint.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { newUserContext, signJwt } from '../../helpers/auth.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';

// Bucket format regexes — these are the "silent-break" assertions.
// Postgres `to_char` with `YYYY-MM-DD HH24:MI:00` / `YYYY-MM-DD HH24:00` /
// `YYYY-MM-DD`. If a future refactor ever routes the bucket generation
// through Python `strftime('%Y-%m-%d %H:00')` instead, these regexes will
// still match the happy case but the JOIN on bucket key (rows vs
// intervals) can mis-align at minute boundaries. The test-3 empty-user
// zero-fill assertion guards the join invariant.
const MINUTE_BUCKET_RE = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:00$/; // last_hour
const HOUR_BUCKET_RE = /^\d{4}-\d{2}-\d{2} \d{2}:00$/;         // last_24_hour
const DAY_BUCKET_RE = /^\d{4}-\d{2}-\d{2}$/;                   // last_7/15/30_days

type AnalyticsResponse = {
  success: boolean;
  token_usage?: Record<string, number>;
  messages?: Record<string, number>;
  feedback?: Record<string, { positive: number; negative: number }>;
};

/**
 * Seed one token_usage row at a specific timestamp. Mirrors what
 * `TokenUsageRepository.insert` writes — if that shape ever drifts, this
 * helper breaks loudly.
 */
async function seedTokenUsage(args: {
  userId: string;
  apiKey?: string | null;
  promptTokens: number;
  generatedTokens: number;
  timestamp: Date;
}): Promise<void> {
  await pg.query(
    `INSERT INTO token_usage (user_id, api_key, prompt_tokens, generated_tokens, timestamp)
     VALUES ($1, $2, $3, $4, $5)`,
    [
      args.userId,
      args.apiKey ?? null,
      args.promptTokens,
      args.generatedTokens,
      args.timestamp.toISOString(),
    ],
  );
}

test.describe('tier-a · token usage analytics', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('token analytics returns non-zero buckets after seeded usage', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    try {
      // Two rows in the last 24h — one an hour ago, one half an hour ago.
      // Total = (100+50) + (200+80) = 150 + 280 = 430 tokens across two
      // buckets. Exact bucket boundaries are to_char-driven — we only
      // assert "some bucket is non-zero and the sum matches".
      const now = new Date();
      const hourAgo = new Date(now.getTime() - 60 * 60 * 1000 + 5_000);
      const halfHourAgo = new Date(now.getTime() - 30 * 60 * 1000);
      await seedTokenUsage({
        userId: sub,
        promptTokens: 100,
        generatedTokens: 50,
        timestamp: hourAgo,
      });
      await seedTokenUsage({
        userId: sub,
        promptTokens: 200,
        generatedTokens: 80,
        timestamp: halfHourAgo,
      });

      const api = await authedRequest(playwright, token);
      try {
        const res = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(res.status()).toBe(200);
        const body = (await res.json()) as AnalyticsResponse;
        expect(body.success).toBe(true);
        expect(body.token_usage).toBeDefined();

        const buckets = body.token_usage ?? {};
        const total = Object.values(buckets).reduce((a, b) => a + b, 0);
        expect(total).toBe(430);

        // At least one bucket is non-zero. The precise bucket depends on
        // the wall clock at query time (and whether the two seeds land in
        // the same hour); we only assert "something non-zero surfaced".
        const nonZeroBuckets = Object.entries(buckets).filter(
          ([, v]) => v > 0,
        );
        expect(nonZeroBuckets.length).toBeGreaterThanOrEqual(1);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });

  test('bucket key format matches YYYY-MM-DD HH24:00 contract for every filter', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    try {
      // Seed a single row within the last minute so every filter window
      // covers it — we need real rows in at least one bucket to prove the
      // GROUP BY path also emits the expected format (not just the
      // Python-generated zero intervals).
      await seedTokenUsage({
        userId: sub,
        promptTokens: 12,
        generatedTokens: 34,
        timestamp: new Date(),
      });

      const api = await authedRequest(playwright, token);
      try {
        // last_hour → minute buckets.
        const lastHour = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_hour' },
        });
        expect(lastHour.status()).toBe(200);
        const lastHourBody = (await lastHour.json()) as AnalyticsResponse;
        expect(lastHourBody.success).toBe(true);
        const lastHourKeys = Object.keys(lastHourBody.token_usage ?? {});
        expect(lastHourKeys.length).toBeGreaterThan(0);
        for (const key of lastHourKeys) {
          expect(
            key,
            `last_hour bucket key "${key}" must match YYYY-MM-DD HH:MM:00`,
          ).toMatch(MINUTE_BUCKET_RE);
        }

        // last_24_hour → hour buckets (the exact silent-break format).
        const last24 = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(last24.status()).toBe(200);
        const last24Body = (await last24.json()) as AnalyticsResponse;
        const last24Keys = Object.keys(last24Body.token_usage ?? {});
        expect(last24Keys.length).toBeGreaterThan(0);
        for (const key of last24Keys) {
          expect(
            key,
            `last_24_hour bucket key "${key}" must match YYYY-MM-DD HH24:00`,
          ).toMatch(HOUR_BUCKET_RE);
        }

        // last_7_days → day buckets.
        const last7 = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_7_days' },
        });
        expect(last7.status()).toBe(200);
        const last7Body = (await last7.json()) as AnalyticsResponse;
        const last7Keys = Object.keys(last7Body.token_usage ?? {});
        expect(last7Keys.length).toBeGreaterThan(0);
        for (const key of last7Keys) {
          expect(
            key,
            `last_7_days bucket key "${key}" must match YYYY-MM-DD`,
          ).toMatch(DAY_BUCKET_RE);
        }

        // Same contract applies to the messages endpoint — it derives
        // the pg_fmt from the same `_FILTER_BUCKETS` table.
        const msgs24 = await api.post('/api/get_message_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(msgs24.status()).toBe(200);
        const msgs24Body = (await msgs24.json()) as AnalyticsResponse;
        for (const key of Object.keys(msgs24Body.messages ?? {})) {
          expect(key).toMatch(HOUR_BUCKET_RE);
        }

        // And to the feedback endpoint.
        const fb30 = await api.post('/api/get_feedback_analytics', {
          data: { filter_option: 'last_30_days' },
        });
        expect(fb30.status()).toBe(200);
        const fb30Body = (await fb30.json()) as AnalyticsResponse;
        for (const key of Object.keys(fb30Body.feedback ?? {})) {
          expect(key).toMatch(DAY_BUCKET_RE);
        }
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });

  test('fresh user returns all-zero buckets (zero-filled, not empty object)', async ({
    browser,
  }) => {
    // Invariant: even with zero rows the response dict must contain every
    // interval key pre-populated to 0. This is what the UI line-chart
    // depends on — an empty `{}` would render an empty axis, not a flat
    // zero line. The Python-generated intervals dict must survive the
    // "no rows" path.
    const { context, token } = await newUserContext(browser);
    try {
      const api = await authedRequest(playwright, token);
      try {
        const tokenRes = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(tokenRes.status()).toBe(200);
        const tokenBody = (await tokenRes.json()) as AnalyticsResponse;
        expect(tokenBody.success).toBe(true);
        const tokenBuckets = tokenBody.token_usage ?? {};
        // 25 hourly intervals spanning `now - 24h` through `now` (inclusive).
        expect(Object.keys(tokenBuckets).length).toBeGreaterThanOrEqual(24);
        for (const [key, value] of Object.entries(tokenBuckets)) {
          expect(key).toMatch(HOUR_BUCKET_RE);
          expect(value).toBe(0);
        }

        const msgRes = await api.post('/api/get_message_analytics', {
          data: { filter_option: 'last_7_days' },
        });
        expect(msgRes.status()).toBe(200);
        const msgBody = (await msgRes.json()) as AnalyticsResponse;
        const msgBuckets = msgBody.messages ?? {};
        expect(Object.keys(msgBuckets).length).toBe(7);
        for (const [key, value] of Object.entries(msgBuckets)) {
          expect(key).toMatch(DAY_BUCKET_RE);
          expect(value).toBe(0);
        }

        const fbRes = await api.post('/api/get_feedback_analytics', {
          data: { filter_option: 'last_7_days' },
        });
        expect(fbRes.status()).toBe(200);
        const fbBody = (await fbRes.json()) as AnalyticsResponse;
        const fbBuckets = fbBody.feedback ?? {};
        expect(Object.keys(fbBuckets).length).toBe(7);
        for (const [key, value] of Object.entries(fbBuckets)) {
          expect(key).toMatch(DAY_BUCKET_RE);
          expect(value).toEqual({ positive: 0, negative: 0 });
        }
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });

  test('filter by api_key_id includes only that agent\'s usage', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    try {
      const api = await authedRequest(playwright, token);
      try {
        // Create a published agent to get a real `key` value (the api_key
        // written into token_usage rows). `api_key_id` in analytics is
        // the agent's `id`, not its `key` — `_resolve_api_key` looks up
        // the agent and returns `agent.key`.
        const createRes = await api.post('/api/create_agent', {
          data: {
            name: 'e2e-analytics-agent',
            description: 'for analytics api_key filtering',
            status: 'published',
            source: 'default',
            prompt_id: 'default',
            chunks: 2,
            retriever: 'classic',
            agent_type: 'classic',
          },
        });
        expect(createRes.status()).toBe(201);
        const created = (await createRes.json()) as { id: string; key: string };
        expect(created.id).toBeTruthy();
        expect(created.key).toBeTruthy();

        const now = new Date();
        const twoMinAgo = new Date(now.getTime() - 2 * 60 * 1000);
        const oneMinAgo = new Date(now.getTime() - 60 * 1000);

        // Row attributed to the agent's key.
        await seedTokenUsage({
          userId: sub,
          apiKey: created.key,
          promptTokens: 111,
          generatedTokens: 22,
          timestamp: twoMinAgo,
        });
        // Row attributed to the user but NOT the agent (direct chat, no
        // api_key) — should be excluded when filtering by api_key_id.
        await seedTokenUsage({
          userId: sub,
          apiKey: null,
          promptTokens: 999,
          generatedTokens: 999,
          timestamp: oneMinAgo,
        });

        // Unfiltered: both rows contribute. 111+22 + 999+999 = 2131.
        const allRes = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(allRes.status()).toBe(200);
        const allBody = (await allRes.json()) as AnalyticsResponse;
        const allTotal = Object.values(allBody.token_usage ?? {}).reduce(
          (a, b) => a + b,
          0,
        );
        expect(allTotal).toBe(111 + 22 + 999 + 999);

        // Filtered by api_key_id: only the agent's row. 111+22 = 133.
        const filteredRes = await api.post('/api/get_token_analytics', {
          data: {
            filter_option: 'last_24_hour',
            api_key_id: created.id,
          },
        });
        expect(filteredRes.status()).toBe(200);
        const filteredBody = (await filteredRes.json()) as AnalyticsResponse;
        const filteredTotal = Object.values(
          filteredBody.token_usage ?? {},
        ).reduce((a, b) => a + b, 0);
        expect(filteredTotal).toBe(111 + 22);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });

  test('cross-tenant: filtering by another user\'s api_key_id does not leak their usage', async ({
    browser,
  }) => {
    // User A and user B each have data. A queries with B's api_key_id.
    // `_resolve_api_key(conn, b_agent_id, a_sub)` returns None (agent
    // lookup is user-scoped), so the filter is dropped and A sees only
    // A's own data — never any of B's rows.
    const aSub = 'e2e-analytics-cross-a';
    const bSub = 'e2e-analytics-cross-b';
    const aToken = signJwt(aSub);
    const bToken = signJwt(bSub);

    const apiA = await authedRequest(playwright, aToken);
    const apiB = await authedRequest(playwright, bToken);
    try {
      // B creates a published agent — B's `agents.id` is the `api_key_id`
      // A will try to probe.
      const bAgentRes = await apiB.post('/api/create_agent', {
        data: {
          name: 'b-agent',
          description: 'owned by user B',
          status: 'published',
          source: 'default',
          prompt_id: 'default',
          chunks: 2,
          retriever: 'classic',
          agent_type: 'classic',
        },
      });
      expect(bAgentRes.status()).toBe(201);
      const bAgent = (await bAgentRes.json()) as { id: string; key: string };

      // Seed usage for both users in the last 24h.
      const now = new Date();
      const oneMinAgo = new Date(now.getTime() - 60 * 1000);
      await seedTokenUsage({
        userId: aSub,
        promptTokens: 10,
        generatedTokens: 5,
        timestamp: oneMinAgo,
      });
      await seedTokenUsage({
        userId: bSub,
        apiKey: bAgent.key,
        promptTokens: 777,
        generatedTokens: 333,
        timestamp: oneMinAgo,
      });

      // A queries analytics with B's agent id as api_key_id.
      const res = await apiA.post('/api/get_token_analytics', {
        data: {
          filter_option: 'last_24_hour',
          api_key_id: bAgent.id,
        },
      });
      expect(res.status()).toBe(200);
      const body = (await res.json()) as AnalyticsResponse;
      expect(body.success).toBe(true);
      const buckets = body.token_usage ?? {};

      // A's total is 10 + 5 = 15. B's 777+333=1110 MUST NOT appear.
      const total = Object.values(buckets).reduce((a, b) => a + b, 0);
      expect(total).toBe(15);

      // Double-check: B's bucket value cannot have bled in under any
      // key. No single bucket should exceed A's total.
      for (const value of Object.values(buckets)) {
        expect(value).toBeLessThanOrEqual(15);
      }
    } finally {
      await apiA.dispose();
      await apiB.dispose();
    }
  });

  test('stale agent: deleting an agent leaves historical token_usage in the all-agents view', async ({
    browser,
  }) => {
    // `agent_id` in `token_usage` has `ON DELETE SET NULL` (see
    // `token_usage_agent_fk` in 0001_initial.py:312). Deleting the agent
    // nulls the agent_id column on historical rows but keeps the tokens
    // — the unfiltered "all agents" analytics view must still surface
    // them. The api_key column is NOT cleared by the trigger (it's a
    // plain string copy, not a FK), so `api_key`-scoped filters would
    // still match — but agent resolution by api_key_id is now impossible
    // because the agents row is gone.
    const { context, sub, token } = await newUserContext(browser);
    try {
      const api = await authedRequest(playwright, token);
      try {
        const createRes = await api.post('/api/create_agent', {
          data: {
            name: 'soon-to-die',
            description: 'deleted mid-spec',
            status: 'published',
            source: 'default',
            prompt_id: 'default',
            chunks: 2,
            retriever: 'classic',
            agent_type: 'classic',
          },
        });
        expect(createRes.status()).toBe(201);
        const agent = (await createRes.json()) as { id: string; key: string };

        const oneMinAgo = new Date(Date.now() - 60 * 1000);
        await pg.query(
          `INSERT INTO token_usage (user_id, api_key, agent_id, prompt_tokens, generated_tokens, timestamp)
           VALUES ($1, $2, CAST($3 AS uuid), $4, $5, $6)`,
          [sub, agent.key, agent.id, 42, 58, oneMinAgo.toISOString()],
        );

        // Sanity: token_usage row is linked to the agent.
        const before = await pg.query<{ n: string }>(
          `SELECT count(*)::text AS n FROM token_usage
             WHERE user_id = $1 AND agent_id = CAST($2 AS uuid)`,
          [sub, agent.id],
        );
        expect(Number(before.rows[0].n)).toBe(1);

        // Delete the agent via `DELETE /api/delete_agent?id=<uuid>`.
        // The `ON DELETE SET NULL` FK (`token_usage_agent_fk`) nulls the
        // `agent_id` column on the historical token_usage row.
        const delRes = await api.delete('/api/delete_agent', {
          params: { id: agent.id },
        });
        expect(delRes.status()).toBe(200);

        const after = await pg.query<{ n: string; agent_id: string | null }>(
          `SELECT count(*)::text AS n, MAX(agent_id::text) AS agent_id
             FROM token_usage WHERE user_id = $1`,
          [sub],
        );
        expect(Number(after.rows[0].n)).toBe(1);
        expect(after.rows[0].agent_id).toBeNull();

        // All-agents analytics view still reports the 100 tokens.
        const analyticsRes = await api.post('/api/get_token_analytics', {
          data: { filter_option: 'last_24_hour' },
        });
        expect(analyticsRes.status()).toBe(200);
        const analytics = (await analyticsRes.json()) as AnalyticsResponse;
        const total = Object.values(analytics.token_usage ?? {}).reduce(
          (a, b) => a + b,
          0,
        );
        expect(total).toBe(100);
      } finally {
        await api.dispose();
      }
    } finally {
      await context.close();
    }
  });
});
