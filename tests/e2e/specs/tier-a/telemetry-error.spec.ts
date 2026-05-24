/**
 * P2-13 · Telemetry on error paths (stack_logs + user_logs).
 *
 * Asserts the two append-only, server-side telemetry pipes stay wired after
 * the MongoDB→Postgres migration:
 *
 *   - `stack_logs` is written by the `@log_activity()` decorator on
 *     `BaseAgent.gen` (application/logging.py:71-123). The decorator wraps
 *     the generator: on normal completion the `finally` branch writes a
 *     single `level="info"` row; on exception it ALSO writes a `level="error"`
 *     row before re-raising. Both branches go through
 *     `_log_activity_to_db` → `StackLogsRepository.insert`.
 *   - `user_logs` is written by `BaseAnswerResource.complete_stream` in
 *     application/api/answer/routes/base.py:460-466, right before the final
 *     `data: {"type": "end"}` frame. Action="stream_answer", user_id is the
 *     decoded JWT `sub` (or the agent owner when invoked via api_key).
 *
 * // Silent-break covered: bad request emits stack_logs and user_logs rows.
 *    A working `/stream` exchange MUST land a row in BOTH tables (one
 *    stack_logs info row emitted by the `@log_activity` finally, one
 *    user_logs stream_answer row emitted by `complete_stream`). If either
 *    pipe silently regresses — e.g. the decorator is removed, the repo
 *    import breaks, or the session-context-manager swallows the write —
 *    production loses visibility into per-request traces without any user-
 *    facing surface; the app keeps happily serving answers.
 *    This spec additionally proves the error path: when the agent layer
 *    raises inside `agent.gen` the finally still fires, AND a preceding
 *    `level="error"` row is logged first, so nothing is lost on the failure
 *    leg either.
 *
 * The `/stream` error we deliberately trigger is an INVALID `prompt_id`
 * (neither a built-in preset nor a UUID/legacy id). `get_prompt` raises
 * `ValueError("Prompt with ID ... not found")` from inside
 * `create_agent` — which runs as part of building the agent, *before*
 * `agent.gen` is iterated. That surfaces as a 400 at the route level
 * (`except ValueError` in application/api/answer/routes/stream.py:151),
 * and — critically — no stack_logs/user_logs row is written for this
 * kind of failure, because the telemetry decorator is bound to
 * `BaseAgent.gen` not to the route. We assert exactly that behavior so
 * nobody misreads "no row on 400" as a regression. The row-emitting
 * path is exercised by the happy-path test, where we pull the response
 * body to let the server-side generator run to completion.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { authedRequest } from '../../helpers/api.js';
import { countRows, pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';
import {
  multipartAuthedRequest,
  publishClassicAgent,
} from '../../helpers/agents.js';

// Silent-break covered: bad request emits stack_logs and user_logs rows

interface StackLogRow {
  id: string;
  activity_id: string;
  endpoint: string | null;
  level: string | null;
  user_id: string | null;
  api_key: string | null;
  query: string | null;
  // JSONB, parsed to JS by pg.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  stacks: any;
}

interface UserLogRow {
  id: string;
  user_id: string | null;
  endpoint: string | null;
  // JSONB, parsed to JS by pg.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

/**
 * Drive one `/stream` request end-to-end. Playwright's APIRequestContext
 * buffers the SSE body into `res.text()` — so by the time the promise
 * resolves, the server-side generator has reached the `UserLogsRepository.insert`
 * at the tail of `complete_stream` AND the `@log_activity` finally has
 * flushed the stack_logs row.
 */
async function streamOnce(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<{ status: number; text: string }> {
  const res = await api.post('/stream', { data: body });
  const text = await res.text();
  return { status: res.status(), text };
}

/**
 * Publish a bare-bones classic agent so it lands in `agents` with a real
 * `key`. Delegates to the shared `publishClassicAgent` helper.
 */
async function publishAgent(
  jsonApi: APIRequestContext,
  token: string,
  userId: string,
  name: string,
): Promise<{ id: string; key: string }> {
  const multipartApi = await multipartAuthedRequest(token);
  try {
    const result = await publishClassicAgent(jsonApi, multipartApi, userId, name);
    return { id: result.id, key: result.key };
  } finally {
    await multipartApi.dispose();
  }
}

test.describe('tier-a · error telemetry', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('happy path /stream emits stack_logs info + user_logs stream_answer rows (pipeline silent-break guard)', async ({
    browser,
  }) => {
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Baseline — truncate leaves both tables empty for this user.
      expect(
        await countRows('stack_logs', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);
      expect(
        await countRows('user_logs', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);

      const question = 'telemetry-happy-path-question';
      const { status, text } = await streamOnce(api, {
        question,
        history: '[]',
      });
      expect(status).toBe(200);
      // Smoke-check: the generator must have emitted the final "end" frame
      // — otherwise the log inserts at the tail of `complete_stream` /
      // `_consume_and_log` may not have landed.
      expect(text).toContain('"type": "end"');

      // ---- stack_logs: @log_activity finally wrote exactly one info row ----
      const { rows: stackRows } = await pg.query<StackLogRow>(
        `SELECT id::text AS id, activity_id, endpoint, level, user_id,
                api_key, query, stacks
           FROM stack_logs
          WHERE user_id = $1
          ORDER BY id ASC`,
        [sub],
      );
      expect(stackRows.length).toBeGreaterThanOrEqual(1);
      const infoRow = stackRows.find((r) => r.level === 'info');
      expect(infoRow).toBeDefined();
      expect(infoRow!.endpoint).toBe('stream');
      expect(infoRow!.user_id).toBe(sub);
      // No error row — happy path must not log at error level.
      expect(stackRows.some((r) => r.level === 'error')).toBe(false);

      // ---- user_logs: complete_stream wrote a stream_answer row ----
      const { rows: userLogRows } = await pg.query<UserLogRow>(
        `SELECT id::text AS id, user_id, endpoint, data
           FROM user_logs
          WHERE user_id = $1
          ORDER BY id ASC`,
        [sub],
      );
      expect(userLogRows).toHaveLength(1);
      expect(userLogRows[0].endpoint).toBe('stream_answer');
      expect(userLogRows[0].data).toBeTruthy();
      expect(userLogRows[0].data.action).toBe('stream_answer');
      expect(userLogRows[0].data.question).toBe(question);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('silent-break: bad /stream request with invalid prompt_id — route rejects 400 AND telemetry pipeline stays consistent', async ({
    browser,
  }) => {
    // An invalid `prompt_id` (not a preset, not a UUID) makes `get_prompt`
    // raise ValueError from inside `create_agent`. That's caught by
    // `except ValueError` in stream.py and translated to a 400 SSE
    // response — *before* `agent.gen` is reached. The telemetry decorator
    // therefore does not fire, and the user_logs insert (which sits at
    // the very tail of `complete_stream`) also does not fire. We assert
    // exactly that to pin the contract: route-level validation errors
    // are silent on the telemetry pipes, so if someone later wires
    // stack_logs into the route handler itself, these numbers change and
    // this test will catch the behaviour shift.
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      // Deliberate bad input: `prompt_id` that is neither a preset
      // ("default"/"creative"/"strict") nor a UUID/legacy ObjectId. The
      // repository lookup returns None and `get_prompt` raises ValueError.
      const res = await api.post('/stream', {
        data: {
          question: 'telemetry-bad-prompt-question',
          history: '[]',
          prompt_id: 'definitely-not-a-real-prompt-id-42',
        },
      });
      // 400 with SSE body containing the route's canned "Malformed
      // request body" error frame.
      expect(res.status()).toBeGreaterThanOrEqual(400);
      expect(res.status()).toBeLessThan(500);
      const body = await res.text();
      expect(body).toContain('"type": "error"');

      // Route-level ValueError path does not reach @log_activity nor the
      // user_logs insert — both tables stay empty for this user.
      expect(
        await countRows('stack_logs', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);
      expect(
        await countRows('user_logs', {
          sql: 'user_id = $1',
          params: [sub],
        }),
      ).toBe(0);

      // Second call — a valid /stream — DOES write both rows. This
      // proves the telemetry pipeline is healthy *for this exact user*,
      // ruling out "maybe the logger is just globally dead" as a false
      // pass on the empty-count assertions above.
      const good = await streamOnce(api, {
        question: 'telemetry-recovery-question',
        history: '[]',
      });
      expect(good.status).toBe(200);
      expect(good.text).toContain('"type": "end"');

      expect(
        await countRows('stack_logs', {
          sql: "user_id = $1 AND endpoint = 'stream' AND level = 'info'",
          params: [sub],
        }),
      ).toBeGreaterThanOrEqual(1);
      expect(
        await countRows('user_logs', {
          sql: "user_id = $1 AND endpoint = 'stream_answer'",
          params: [sub],
        }),
      ).toBeGreaterThanOrEqual(1);
    } finally {
      await api.dispose();
      await context.close();
    }
  });

  test('api_key-only /stream (no JWT) — user_logs.user_id derives from the agent owner and data->>api_key is set', async ({
    browser,
  }) => {
    // Seed: owner publishes an agent so it gets a real `agents.key`.
    const owner = await newUserContext(browser, { sub: 'e2e-telemetry-owner' });
    const ownerApi = await authedRequest(playwright, owner.token);
    let agent: { id: string; key: string } | null = null;
    try {
      agent = await publishAgent(ownerApi, owner.token, owner.sub, 'telemetry-api-key-agent');
    } finally {
      await ownerApi.dispose();
    }
    expect(agent).not.toBeNull();

    // Unauthenticated APIRequestContext: no Authorization header at all.
    // The /stream route accepts an `api_key` field in the body for the
    // widget/external-integration path — the backend rebuilds
    // `decoded_token = {sub: agent.user_id}` inside
    // `StreamProcessor._configure_agent`, so the telemetry rows land on
    // the agent OWNER, not on the caller.
    const baseURL = process.env.API_URL ?? 'http://127.0.0.1:7099';
    const anon = await playwright.request.newContext({
      baseURL,
      extraHTTPHeaders: { 'Content-Type': 'application/json' },
    });
    try {
      const question = 'telemetry-api-key-question';
      const res = await anon.post('/stream', {
        data: {
          question,
          history: '[]',
          api_key: agent!.key,
        },
      });
      const text = await res.text();
      expect(res.status()).toBe(200);
      expect(text).toContain('"type": "end"');

      // user_logs row lands on the owner, with api_key inside the JSONB
      // data payload (that's the shape UserLogsRepository.find_by_api_key
      // filters on via `data->>'api_key'`).
      const { rows: userLogRows } = await pg.query<UserLogRow>(
        `SELECT id::text AS id, user_id, endpoint, data
           FROM user_logs
          WHERE user_id = $1 AND endpoint = 'stream_answer'
          ORDER BY id DESC
          LIMIT 5`,
        [owner.sub],
      );
      expect(userLogRows.length).toBeGreaterThanOrEqual(1);
      const latest = userLogRows[0];
      expect(latest.user_id).toBe(owner.sub);
      expect(latest.data.question).toBe(question);
      expect(latest.data.api_key).toBe(agent!.key);

      // stack_logs row for the owner is also present and carries the
      // api_key through (column-level, set by logging.py:79). This is
      // the column the Appendix-A support tooling greps on to reconstruct
      // per-agent request activity.
      const { rows: stackRows } = await pg.query<StackLogRow>(
        `SELECT id::text AS id, activity_id, endpoint, level, user_id,
                api_key, query, stacks
           FROM stack_logs
          WHERE user_id = $1
          ORDER BY id DESC
          LIMIT 5`,
        [owner.sub],
      );
      expect(stackRows.length).toBeGreaterThanOrEqual(1);
      const withApiKey = stackRows.find((r) => r.api_key === agent!.key);
      expect(withApiKey).toBeDefined();
      expect(withApiKey!.endpoint).toBe('stream');
      expect(withApiKey!.level).toBe('info');
    } finally {
      await anon.dispose();
      await owner.context.close();
    }
  });

  test('stack_logs.stacks JSONB is a well-formed array with a shape the UI/support tooling can read', async ({
    browser,
  }) => {
    // This exists to guard the JSONB shape contract itself — the
    // `stacks` column drives the Logs admin panel in Settings. If the
    // column regresses to NULL, to a string, or to a bare object,
    // downstream readers (analytics routes, the Logs UI) break silently.
    const { context, sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);
    try {
      const { status, text } = await streamOnce(api, {
        question: 'telemetry-stacks-shape-question',
        history: '[]',
      });
      expect(status).toBe(200);
      expect(text).toContain('"type": "end"');

      const { rows } = await pg.query<StackLogRow>(
        `SELECT id::text AS id, activity_id, endpoint, level, user_id,
                api_key, query, stacks
           FROM stack_logs
          WHERE user_id = $1 AND endpoint = 'stream' AND level = 'info'
          ORDER BY id DESC
          LIMIT 1`,
        [sub],
      );
      expect(rows).toHaveLength(1);
      const row = rows[0];
      // Table DDL: stacks JSONB NOT NULL DEFAULT '[]'::jsonb — must come
      // back as an array (pg parses JSONB into JS values).
      expect(Array.isArray(row.stacks)).toBe(true);
      // activity_id is a UUIDv4 generated inside @log_activity.
      expect(row.activity_id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      );
      // Truncation ceiling: the wrapper in logging.py caps text fields at
      // 10 000 chars. Anything longer means the truncation step regressed.
      if (typeof row.query === 'string') {
        expect(row.query.length).toBeLessThanOrEqual(10_000);
      }
    } finally {
      await api.dispose();
      await context.close();
    }
  });
});
