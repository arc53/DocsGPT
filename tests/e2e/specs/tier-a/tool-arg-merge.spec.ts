/**
 * Streaming tool-call argument merge — the "silent tool" failure.
 *
 * Production incident (2026-08-19, a brand-new user's first session): every
 * call to one tool failed to parse for six minutes, the model kept re-emitting
 * it, the tool never ran once — and every stream still finished `ok`, so the
 * stream error rate never moved. 22 `tool_call_attempts` rows landed with
 * `tool_name='unknown'`; the parser logged `Extra data: line 1 column 3
 * (char 2)`, which is `json.loads` reporting that it consumed a COMPLETE
 * two-character JSON value (`{}`) and then found more input.
 *
 * Mechanism. `LLMHandler.handle_streaming` merges streamed tool-call deltas
 * keyed by `call.index`, and when both sides are `str` it APPENDS
 * (application/llm/handlers/base.py:1419-1428). Its `else` branch is commented
 * "Complete (non-delta) payloads: latest wins" but only fires on a type
 * mismatch. So a provider that restates a COMPLETE `arguments` payload on a
 * second frame for the same index gets them concatenated into invalid JSON.
 * Only OpenAI-compatible providers reach this branch — Anthropic and Google
 * emit index-less ToolCalls that take the separate "complete call" path at
 * base.py:1408-1412.
 *
 * // Silent-break covered: the tool never runs, yet the turn reports success.
 *    A regression here is invisible to every error-rate metric we have — the
 *    only durable evidence is `tool_call_attempts.tool_name = 'unknown'`.
 *    These specs assert on that row, not on the SSE text.
 *
 * The `once` and `delta` cases are the boundary: they prove the frames
 * themselves are fine and that legitimate partial-delta accumulation — which
 * is the entire reason the `+=` exists — must keep working. Any fix that
 * makes `repeat` pass MUST leave those two green.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import { authedRequest } from '../../helpers/api.js';
import { pg } from '../../helpers/db.js';
import { resetDb } from '../../helpers/reset.js';
import { newUserContext } from '../../helpers/auth.js';

/**
 * `memory` ships in DEFAULT_CHAT_TOOLS, so `memory_view` is a registered,
 * runnable action for every user — the point being that this tool COULD have
 * run. Production's victim was `note_view`, the same shape.
 */
const ACTION = 'memory_view';

/** Directive understood by scripts/e2e/mock_llm.py. */
function toolCallDirective(
  action: string,
  mode: 'once' | 'repeat' | 'delta',
  args?: Record<string, unknown>,
): string {
  const base = `[[MOCK_LLM_TOOLCALL:${action}:${mode}`;
  if (args === undefined) return `${base}]]`;
  const encoded = Buffer.from(JSON.stringify(args), 'utf8').toString('base64url');
  return `${base}:${encoded}]]`;
}

interface AttemptRow {
  tool_name: string;
  action_name: string;
  status: string;
  error: string | null;
}

async function attemptsFor(userId: string): Promise<AttemptRow[]> {
  const { rows } = await pg.query<AttemptRow>(
    `SELECT tool_name, action_name, status, error
       FROM tool_call_attempts
      WHERE user_id = $1
      ORDER BY attempted_at ASC`,
    [userId],
  );
  return rows;
}

async function messageStatuses(userId: string): Promise<string[]> {
  const { rows } = await pg.query<{ status: string }>(
    `SELECT status FROM conversation_messages WHERE user_id = $1 ORDER BY position ASC`,
    [userId],
  );
  return rows.map((r) => r.status);
}

test.describe('streaming tool-call argument merge', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a provider that restates complete arguments makes the tool unrunnable, and the turn still reports success', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    try {
      const res = await api.post('/stream', {
        data: {
          question: `check my memory ${toolCallDirective(ACTION, 'repeat')}`,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(res.ok()).toBeTruthy();
      const body = await res.text();

      // ---- the failure is silent by every signal a user or a dashboard sees
      expect(body).toContain('"type": "end"');
      expect(await messageStatuses(sub)).toEqual(['complete']);

      // ---- ...and total by the only signal that records it
      const attempts = await attemptsFor(sub);
      expect(attempts.length).toBeGreaterThan(0);
      expect(attempts.every((a) => a.status === 'failed')).toBe(true);
      // `tool_name` is 'unknown' because parsing dies before the name is
      // resolved — the production fingerprint.
      expect(attempts.every((a) => a.tool_name === 'unknown')).toBe(true);
      expect(attempts.every((a) => a.action_name === ACTION)).toBe(true);
      // The tool itself never executed: not one attempt reached the registry.
      expect(attempts.some((a) => a.tool_name === 'memory')).toBe(false);
    } finally {
      await api.dispose();
    }
  });

  test('the same call succeeds when the provider sends its arguments once', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    try {
      const res = await api.post('/stream', {
        data: {
          question: `check my memory ${toolCallDirective(ACTION, 'once', { path: '/' })}`,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(res.ok()).toBeTruthy();

      const attempts = await attemptsFor(sub);
      expect(attempts.length).toBeGreaterThan(0);
      // Resolved to the real tool — so the frames are not the problem.
      expect(attempts.some((a) => a.tool_name === 'unknown')).toBe(false);
      expect(attempts[0].tool_name).toBe('memory');
      expect(attempts[0].action_name).toBe(ACTION);
    } finally {
      await api.dispose();
    }
  });

  test('legitimate partial-delta arguments still reassemble', async ({ browser }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    try {
      const res = await api.post('/stream', {
        data: {
          question: `check my memory ${toolCallDirective(ACTION, 'delta', { path: '/' })}`,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(res.ok()).toBeTruthy();

      const attempts = await attemptsFor(sub);
      expect(attempts.length).toBeGreaterThan(0);
      // This is what the `+=` in the merge exists for. A fix for `repeat`
      // that breaks this case has traded one bug for a worse one.
      expect(attempts.some((a) => a.tool_name === 'unknown')).toBe(false);
      expect(attempts[0].tool_name).toBe('memory');
    } finally {
      await api.dispose();
    }
  });

  test('a registered tool with unparseable arguments is re-asked every round, up to the iteration cap', async ({
    browser,
  }) => {
    const { sub, token } = await newUserContext(browser);
    const api = await authedRequest(playwright, token);

    try {
      const res = await api.post('/stream', {
        data: {
          question: `check my memory ${toolCallDirective(ACTION, 'repeat')}`,
          save_conversation: true,
        },
        timeout: 180_000,
      });
      expect(res.ok()).toBeTruthy();
      const body = await res.text();

      // The repeat-failure guard (`UNRESOLVABLE_CALL_LIMIT`,
      // application/agents/tool_executor.py) deliberately does NOT apply here:
      // it is gated on `llm_name not in self._name_to_tool`, i.e. invented tool
      // names only, because "a registered tool whose arguments merely failed to
      // decode is recoverable, and refusing it would strand a working tool for
      // the rest of the turn". `memory_view` is registered, so every round gets
      // the plain error and another chance.
      expect(body).toContain('its arguments were not a valid JSON object');
      expect(body).not.toContain('has already failed');

      // That reasoning holds when the model can fix its own output. It cannot
      // here — the arguments are mangled downstream of the model by the merge,
      // so the retry is unwinnable and the only thing that ends the turn is
      // MAX_TOOL_ITERATIONS (application/llm/handlers/base.py:17). Every one of
      // these 25 rounds is a billed provider call that could never succeed.
      const attempts = await attemptsFor(sub);
      expect(attempts.length).toBe(25);
    } finally {
      await api.dispose();
    }
  });
});
