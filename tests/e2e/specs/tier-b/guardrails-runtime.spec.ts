/**
 * Tier-B · agent guardrails at run time: blocking, streaming redaction, and
 * the decision journal — over real SSE, against the real DB.
 *
 * A guardrail is only worth anything at the moment text crosses a boundary,
 * and every boundary here is a place where a regression is silent:
 *
 * // Silent-break covered #1 — THE ONE THAT MATTERS. Output controls run
 * // inside `StreamingOutputGuard` (application/guardrails/stream.py). Once a
 * // token reaches `_emit` it is on the wire *and* journalled; it cannot be
 * // recalled. The guard therefore holds a lookback tail and detects over
 * // `held + new` rather than over the about-to-emit prefix. If that ever
 * // regresses to scanning only the prefix, a secret split across two model
 * // deltas stops matching and its first half ships to the browser — with no
 * // error, no log line, and a redacted-looking answer. `buildBoundarySplitAnswer`
 * // forces the sensitive literal to straddle a chunk boundary, and the spec
 * // asserts the raw value appears in NO frame, not merely that a placeholder
 * // appeared somewhere.
 *
 * // Silent-break covered #2: a block message rewritten by
 * // `sanitize_api_error`. The guardrail error event carries
 * // `user_facing: true` (application/agents/base.py:_guardrail_block_event);
 * // drop it and `application/api/answer/routes/base.py:656` substring-matches
 * // the operator's own wording and replaces it with a canned network/rate
 * // limit string. The block messages below deliberately contain the word
 * // "quota", which `sanitize_api_error` rewrites to "Rate limit exceeded".
 *
 * // Silent-break covered #3: a mid-stream block that still persists the
 * // leaked prefix. Tokens already sent cannot be recalled, but the stored
 * // message must be the refusal — otherwise reloading the conversation
 * // redisplays exactly what was just blocked.
 *
 * // Silent-break covered #4: `monitor_only` that quietly enforces (breaking
 * // the documented rollout path) or quietly records nothing (making the
 * // rollout path useless because there is no evidence to promote on).
 *
 * // Silent-break covered #5: the audit journal leaking another user's
 * // blocked prompts through `/api/guardrails/events`.
 *
 * Deviations, both flagged deliberately:
 *
 * - Agents are PUBLISHED, and their `sources` row is INSERTed directly. A
 *   published agent is required because `StreamProcessor._configure_agent`
 *   only loads `agents.config` when the agent resolves to an API key, and a
 *   draft row has `key = NULL` (see `publishGuardrailAgent`). The source is
 *   never retrieved from — every request passes `isNoneDoc` — so Celery
 *   ingestion would buy nothing.
 * - The model's exact words are pinned with the mock LLM's in-band
 *   `[[MOCK_LLM_EMIT:…]]` directive rather than a hash fixture, because the
 *   system prompt embeds today's date and a hash fixture rots overnight. See
 *   `helpers/guardrails.ts`.
 */

import * as playwright from '@playwright/test';
const { expect, test } = playwright;

import type { APIRequestContext } from '@playwright/test';

import { multipartAuthedRequest } from '../../helpers/agents.js';
import { authedRequest } from '../../helpers/api.js';
import { signJwt } from '../../helpers/auth.js';
import { countRows, pg } from '../../helpers/db.js';
import {
  buildBoundarySplitAnswer,
  emitDirective,
  mockChunkBoundaries,
  publishGuardrailAgent,
} from '../../helpers/guardrails.js';
import { resetDb } from '../../helpers/reset.js';
import {
  answerText,
  parseSseFrames,
  streamFrames,
  type SseFrame,
} from '../../helpers/streaming.js';

/** A real AWS access key ID shape — matches `SECRET_PATTERNS.AWS_ACCESS_KEY`. */
const AWS_KEY = 'AKIAIOSFODNN7EXAMPLE';
/** Matches `PII_PATTERNS.EMAIL`. */
const EMAIL = 'confidential.person@internal-example.test';

/**
 * The guard sizes its withhold window from the widest match a check can
 * report (`GuardrailCheck.window_for`, defaulting to `max_match_chars`), so an
 * answer shorter than that window is legitimately held whole until flush —
 * correct, but it would leave the incremental release path untested. These
 * answer sizes are chosen to exceed each check's window by more than one model
 * delta, so the release frontier provably sweeps over the sensitive value
 * mid-stream. Keep them above the corresponding `max_match_chars` in
 * `application/guardrails/checks/patterns.py`.
 */
const SECRETS_WINDOW_CHARS = 2048;
const SECRETS_ANSWER_CHARS = 6000;
const PII_WINDOW_CHARS = 256;
const PII_ANSWER_CHARS = 1200;

interface GuardrailEventRow {
  user_id: string | null;
  agent_id: string | null;
  message_id: string | null;
  stage: string;
  check_name: string;
  detector_type: string;
  action: string;
  outcome: string;
  category: string | null;
  match_count: number;
  matched_value: string | null;
  detail: string | null;
}

async function guardrailEvents(agentId: string): Promise<GuardrailEventRow[]> {
  const { rows } = await pg.query<GuardrailEventRow>(
    `SELECT user_id, agent_id::text AS agent_id, message_id::text AS message_id,
            stage, check_name, detector_type, action, outcome, category,
            match_count, matched_value, detail
       FROM guardrail_events
      WHERE agent_id = CAST($1 AS uuid)
      ORDER BY created_at, check_name`,
    [agentId],
  );
  return rows;
}

async function storedMessages(
  userId: string,
): Promise<Array<{ prompt: string | null; response: string | null; id: string }>> {
  const { rows } = await pg.query<{
    id: string;
    prompt: string | null;
    response: string | null;
  }>(
    `SELECT cm.id::text AS id, cm.prompt, cm.response
       FROM conversation_messages cm
       JOIN conversations c ON c.id = cm.conversation_id
      WHERE c.user_id = $1
      ORDER BY cm.position`,
    [userId],
  );
  return rows;
}

/** The `{"type":"id"}` frame's conversation UUID, or null. */
function conversationIdOf(frames: SseFrame[]): string | null {
  const frame = frames.find((f) => f.data?.type === 'id');
  return typeof frame?.data?.id === 'string' ? frame.data.id : null;
}

/** Ask `agentId` a question, pinning the model's reply to `answer`. */
function askWithPinnedAnswer(
  api: APIRequestContext,
  agentId: string,
  question: string,
  answer: string,
) {
  return streamFrames(api, {
    question: `${question} ${emitDirective(answer)}`,
    agent_id: agentId,
    history: '[]',
    isNoneDoc: true,
  });
}

test.describe('tier-b · guardrails · input stage', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a denylist block at input terminates the turn with the operator message and never calls the model', async () => {
    const sub = `e2e-gr-input-block-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'input-block',
        {
          enabled: true,
          mode: 'scan_all',
          block_message:
            'Blocked by policy: this request exceeds your content quota.',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['zebrafish-protocol'] },
            },
          ],
        },
      );

      // A sentinel the model would emit if it were ever reached. Its
      // absence, together with the token_usage assertion below, is what
      // proves the block happened *before* the LLM call rather than after.
      const sentinel = 'MODEL-WAS-REACHED-SENTINEL-4417';
      const { status, frames, text } = await askWithPinnedAnswer(
        json,
        agentId,
        'explain the zebrafish-protocol to me',
        `Here is the answer. ${sentinel}`,
      );

      expect(status).toBe(200);

      const errorFrames = frames.filter((f) => f.data?.type === 'error');
      expect(
        errorFrames,
        `a blocked input must emit exactly one terminal error frame; got frames ${frames
          .map((f) => f.data?.type)
          .join(', ')}`,
      ).toHaveLength(1);
      expect(
        errorFrames[0].data.error,
        'the configured block message must reach the client verbatim — ' +
          'sanitize_api_error would have rewritten "quota" into a rate-limit ' +
          'string had `user_facing: true` been dropped',
      ).toBe('Blocked by policy: this request exceeds your content quota.');
      expect(text).not.toContain('Rate limit exceeded');

      // The retract frame is what tells the client to discard whatever it
      // has rendered for this turn.
      const guardrailFrames = frames.filter(
        (f) => f.data?.type === 'guardrail',
      );
      expect(guardrailFrames).toHaveLength(1);
      expect(guardrailFrames[0].data).toMatchObject({
        retract: true,
        guardrail: {
          stage: 'input',
          categories: ['BANNED_TERM'],
          checks: ['denylist'],
        },
      });

      // No answer text at all, and specifically not the sentinel.
      expect(
        answerText(frames),
        'a blocked input must produce no answer deltas',
      ).toBe('');
      expect(
        text,
        'the model must never be reached when input is blocked',
      ).not.toContain(sentinel);

      // The hard proof: an LLM call always writes a `token_usage` row (see
      // the stream_token_usage decorator in application/usage.py), and this
      // turn is hidden so no title-generation call runs either.
      expect(
        await countRows('token_usage', { sql: 'user_id = $1', params: [sub] }),
        'a blocked input must not spend a single LLM call',
      ).toBe(0);

      // Stream still terminates cleanly — a block is a refusal, not a crash.
      expect(frames[frames.length - 1].data).toEqual({ type: 'end' });

      const events = await guardrailEvents(agentId);
      expect(events).toHaveLength(1);
      expect(events[0]).toMatchObject({
        user_id: sub,
        stage: 'input',
        check_name: 'denylist',
        detector_type: 'DENYLIST',
        action: 'block',
        outcome: 'triggered',
        category: 'BANNED_TERM',
        match_count: 1,
      });
      // GUARDRAILS_STORE_SCANNED_TEXT is off by default: the journal must
      // not become the place the blocked material ends up living.
      expect(
        events[0].matched_value,
        'the scanned text must not be persisted unless the operator opts in',
      ).toBeNull();
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('a clean question through the same guarded agent answers normally', async () => {
    const sub = `e2e-gr-input-clean-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'input-clean',
        {
          enabled: true,
          mode: 'scan_all',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['zebrafish-protocol'] },
            },
          ],
        },
      );

      const answer = 'Pelicans are large water birds with a distinctive pouch.';
      const { status, frames } = await askWithPinnedAnswer(
        json,
        agentId,
        'tell me about pelicans',
        answer,
      );

      expect(status).toBe(200);
      // The control that must NOT fire is the point of this test: without a
      // negative case, a guardrail that blocks everything would pass the
      // suite above.
      expect(frames.some((f) => f.data?.type === 'error')).toBe(false);
      expect(answerText(frames)).toBe(answer);
      expect(await guardrailEvents(agentId)).toHaveLength(0);
      expect(
        await countRows('token_usage', { sql: 'user_id = $1', params: [sub] }),
      ).toBeGreaterThanOrEqual(1);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails · draft agents', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  /**
   * Regression: `_configure_agent` used to load `agents.config` only inside
   * `if effective_key:`, and a draft agent's `key` column is NULL — so
   * `_get_agent_key` returned None and the whole config block was skipped.
   *
   * The consequence was specific and bad: the agent builder's preview
   * ("Test message") posts `agent_id` with no api_key
   * (frontend/src/agents/agentPreviewSlice.ts:128), and the agent under
   * construction is a draft. The one place an operator can try their
   * guardrails before publishing was precisely the place they did not run —
   * the banned answer came straight through and there was no way to tell a
   * misconfigured control from a feature that was off.
   *
   * `_get_agent_key` now stashes the authorized row and `_configure_agent`
   * reads `config` from it on the keyless path.
   */
  test('a draft agent enforces its guardrails so the builder preview can be trusted', async () => {
    const sub = `e2e-gr-draft-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    try {
      // A draft row, exactly as /api/create_agent writes one: no key.
      const { rows } = await pg.query<{ id: string }>(
        `INSERT INTO agents (user_id, name, status, retriever, chunks,
                             agent_type, config)
         VALUES ($1, 'draft with guardrails', 'draft', 'classic', 2,
                 'classic', CAST($2 AS jsonb))
         RETURNING id::text AS id`,
        [
          sub,
          JSON.stringify({
            guardrails: {
              enabled: true,
              mode: 'scan_all',
              fail_open: true,
              timeout_ms: 2000,
              block_message: 'Blocked by policy while still a draft.',
              controls: [
                {
                  check: 'denylist',
                  stage: 'input',
                  action: 'block',
                  enabled: true,
                  settings: {
                    terms: ['zebrafish-protocol'],
                    match: 'word',
                    case_sensitive: false,
                  },
                },
              ],
            },
          }),
        ],
      );
      const agentId = rows[0].id;

      // The payload agentPreviewSlice.ts sends: agent_id, no api_key.
      const { frames } = await askWithPinnedAnswer(
        json,
        agentId,
        'tell me about the zebrafish-protocol',
        'this answer should never be produced',
      );

      expect(
        frames.some((f) => f.data?.type === 'error'),
        'a draft agent must honour its own guardrails, otherwise the builder ' +
          'preview silently tests an unguarded agent',
      ).toBe(true);
    } finally {
      await json.dispose();
    }
  });
});

test.describe('tier-b · guardrails · streaming output redaction', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a secret split across two model deltas is redacted before any byte of it reaches the wire', async () => {
    const sub = `e2e-gr-redact-secret-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const payload = buildBoundarySplitAnswer(AWS_KEY, SECRETS_ANSWER_CHARS);

      // Self-checks: if either of these ever stops holding, the test still
      // passes but stops testing the thing it exists for.
      expect(
        payload.boundaries.some(
          (b) => b > payload.start && b < payload.end,
        ),
        `the secret must straddle a stream chunk boundary; secret occupies ` +
          `[${payload.start},${payload.end}) and boundaries are ` +
          `[${payload.boundaries.join(', ')}]`,
      ).toBe(true);
      expect(
        payload.content.length,
        'the answer must exceed the secrets check window plus one model delta, ' +
          'or the guard legitimately withholds everything until flush and the ' +
          'incremental release path is never exercised',
      ).toBeGreaterThan(SECRETS_WINDOW_CHARS + payload.boundaries[0]);

      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'redact-secret',
        {
          enabled: true,
          mode: 'scan_all',
          controls: [
            { check: 'secrets', stage: 'output', action: 'redact' },
          ],
        },
      );

      const { status, frames, text } = await askWithPinnedAnswer(
        json,
        agentId,
        'summarise the deployment runbook',
        payload.content,
      );
      expect(status).toBe(200);

      const answerFrames = frames.filter((f) => f.data?.type === 'answer');
      expect(
        answerFrames.length,
        'the answer must actually have been released in pieces — a single ' +
          'delta would mean everything was withheld until flush and the ' +
          'mid-stream release path was never exercised',
      ).toBeGreaterThan(1);
      // Stronger: the release frontier must have swept PAST the secret while
      // the stream was still running, not at flush. That is the only moment
      // the lookback window is load-bearing — remove it and the first half of
      // the secret ships in the delta that carries it.
      const releasedBeforeFlush = answerFrames
        .slice(0, -1)
        .map((f) => String(f.data.answer))
        .join('').length;
      expect(
        releasedBeforeFlush,
        `the secret at [${payload.start},${payload.end}) must cross the ` +
          `release frontier mid-stream; only ${releasedBeforeFlush} chars were ` +
          'released before the final delta',
      ).toBeGreaterThan(payload.end);

      // THE assertion. Per-frame first, so a failure names the leaking frame.
      answerFrames.forEach((frame, index) => {
        expect(
          String(frame.data.answer),
          `answer delta ${index} leaked the raw secret`,
        ).not.toContain(AWS_KEY);
      });
      const joined = answerText(frames);
      expect(
        joined,
        'the raw secret must not survive reassembly of the deltas either',
      ).not.toContain(AWS_KEY);
      // And nowhere in the raw SSE body — sources, thought, metadata frames
      // included.
      expect(
        text,
        'the raw secret must not appear anywhere in the SSE body',
      ).not.toContain(AWS_KEY);

      expect(
        joined,
        'the redaction placeholder must be present — an answer that simply ' +
          'dropped the secret silently would also pass the negative checks',
      ).toContain('[REDACTED]');
      // Everything either side of the secret must be untouched: redaction is
      // a mask, not a truncation.
      expect(joined).toContain(payload.content.slice(0, payload.start - 1));
      expect(joined).toContain(payload.content.slice(payload.end + 1));

      // The persisted message must be the redacted text, not the original.
      const messages = await storedMessages(sub);
      expect(messages).toHaveLength(1);
      expect(
        messages[0].response,
        'the raw secret must not be persisted to conversation_messages',
      ).not.toContain(AWS_KEY);
      expect(messages[0].response).toContain('[REDACTED]');

      const events = await guardrailEvents(agentId);
      expect(events.length).toBeGreaterThanOrEqual(1);
      const redactions = events.filter(
        (e) => e.check_name === 'secrets' && e.action === 'redact',
      );
      expect(redactions.length).toBeGreaterThanOrEqual(1);
      expect(redactions[0]).toMatchObject({
        user_id: sub,
        stage: 'output',
        outcome: 'triggered',
        category: 'AWS_ACCESS_KEY',
      });
      expect(
        redactions[0].message_id,
        'a guardrail event must be attributable to the message it fired on',
      ).toBe(messages[0].id);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('an email address split across two model deltas is masked with its entity label', async () => {
    const sub = `e2e-gr-redact-pii-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const payload = buildBoundarySplitAnswer(EMAIL, PII_ANSWER_CHARS);
      expect(
        payload.boundaries.some((b) => b > payload.start && b < payload.end),
        `the email must straddle a stream chunk boundary; occupies ` +
          `[${payload.start},${payload.end}), boundaries [${payload.boundaries.join(', ')}]`,
      ).toBe(true);
      expect(
        payload.content.length,
        'the answer must exceed the pii check window plus one model delta',
      ).toBeGreaterThan(PII_WINDOW_CHARS + payload.boundaries[0]);

      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'redact-pii',
        {
          enabled: true,
          mode: 'scan_all',
          controls: [
            {
              check: 'pii',
              stage: 'output',
              action: 'redact',
              settings: { entities: ['EMAIL'] },
            },
          ],
        },
      );

      const { status, frames, text } = await askWithPinnedAnswer(
        json,
        agentId,
        'who owns the incident runbook',
        payload.content,
      );
      expect(status).toBe(200);

      const answerFrames = frames.filter((f) => f.data?.type === 'answer');
      expect(answerFrames.length).toBeGreaterThan(1);
      answerFrames.forEach((frame, index) => {
        expect(
          String(frame.data.answer),
          `answer delta ${index} leaked the raw email address`,
        ).not.toContain(EMAIL);
      });
      expect(text).not.toContain(EMAIL);
      // PII spans carry no explicit replacement, so `Span.masked_with()`
      // falls back to the entity label — which is what makes a redacted
      // answer readable ("email address here") instead of just mangled.
      expect(answerText(frames)).toContain('[EMAIL]');

      const messages = await storedMessages(sub);
      expect(messages).toHaveLength(1);
      expect(messages[0].response).not.toContain(EMAIL);

      const events = await guardrailEvents(agentId);
      expect(
        events.some(
          (e) =>
            e.check_name === 'pii' &&
            e.stage === 'output' &&
            e.action === 'redact' &&
            e.outcome === 'triggered' &&
            e.category === 'EMAIL',
        ),
        `expected a pii/output/redact event, got ${JSON.stringify(events)}`,
      ).toBe(true);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails · output blocking', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('a block that fires mid-stream stops the answer and persists the refusal, not the leaked prefix', async () => {
    const sub = `e2e-gr-output-block-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const banned = 'zebrafish-protocol';
      const blockMessage =
        'Blocked by policy: the answer exceeded the disclosure quota.';
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'output-block',
        {
          enabled: true,
          mode: 'scan_all',
          block_message: blockMessage,
          controls: [
            {
              check: 'denylist',
              stage: 'output',
              action: 'block',
              settings: { terms: [banned] },
            },
          ],
        },
      );

      // Put the banned term late enough that earlier deltas have already
      // been released — this is the "tokens already on the wire" case, which
      // is the only interesting one for persistence.
      const lead =
        'The incident review concluded that the rollout was uneventful and ' +
        'that no customer data was affected at any point during the change ' +
        'window, which the on-call engineer confirmed in the handover notes ' +
        'the following morning after a full audit of the dashboards. ';
      const content = `${lead}${lead}The internal codename is ${banned} and it must never be shared.`;
      expect(
        content.length,
        'the answer must be long enough for the guard to release a prefix ' +
          'before the banned term arrives',
      ).toBeGreaterThan(500);
      const boundaries = mockChunkBoundaries(content);
      expect(
        content.indexOf(banned),
        `the banned term must land after the first chunk boundary ` +
          `(${boundaries[0]}) so a prefix is already released when it fires`,
      ).toBeGreaterThan(boundaries[0]);

      const { status, frames } = await askWithPinnedAnswer(
        json,
        agentId,
        'what is the internal codename',
        content,
      );
      expect(status).toBe(200);

      const leaked = answerText(frames);
      expect(
        leaked.length,
        'the guard should have released a clean prefix before blocking',
      ).toBeGreaterThan(0);
      expect(
        leaked,
        'the banned term itself must never be released, even though earlier ' +
          'text already was',
      ).not.toContain(banned);

      const errorFrames = frames.filter((f) => f.data?.type === 'error');
      expect(errorFrames).toHaveLength(1);
      expect(
        errorFrames[0].data.error,
        'the block message must survive sanitize_api_error untouched',
      ).toBe(blockMessage);

      const guardrailFrames = frames.filter((f) => f.data?.type === 'guardrail');
      expect(guardrailFrames).toHaveLength(1);
      expect(guardrailFrames[0].data).toMatchObject({
        retract: true,
        guardrail: { stage: 'output', checks: ['denylist'] },
      });

      // ---- reload the conversation --------------------------------------
      const conversationId = conversationIdOf(frames);
      expect(conversationId).toBeTruthy();

      const reload = await json.get(
        `/api/get_single_conversation?id=${encodeURIComponent(conversationId as string)}`,
      );
      expect(reload.status()).toBe(200);
      const body = (await reload.json()) as {
        queries: Array<{ prompt: string; response: string }>;
      };
      expect(body.queries).toHaveLength(1);
      expect(
        body.queries[0].response,
        'reloading the conversation must show the refusal, not the text that ' +
          'was just blocked',
      ).toBe(blockMessage);
      expect(body.queries[0].response).not.toContain(banned);
      expect(
        body.queries[0].response,
        'the prefix that leaked live must not be re-served on reload',
      ).not.toContain(leaked.slice(0, 40));

      const messages = await storedMessages(sub);
      expect(messages).toHaveLength(1);
      expect(messages[0].response).toBe(blockMessage);

      const events = await guardrailEvents(agentId);
      expect(
        events.some(
          (e) =>
            e.stage === 'output' &&
            e.check_name === 'denylist' &&
            e.action === 'block' &&
            e.outcome === 'triggered',
        ),
        `expected a denylist/output/block event, got ${JSON.stringify(events)}`,
      ).toBe(true);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails · monitor_only', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('monitor_only leaves the answer byte-identical while still journalling what it would have done', async () => {
    const sub = `e2e-gr-monitor-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const payload = buildBoundarySplitAnswer(AWS_KEY, SECRETS_ANSWER_CHARS);

      // The SAME control that redacts under scan_all, only the mode differs.
      // `GuardrailsConfig.controls_for` downgrades every action to `flag`
      // (application/guardrails/config.py:129-136) — that downgrade is the
      // documented rollout path, so it has to be exact in both directions:
      // no enforcement, but full evidence.
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'monitor-only',
        {
          enabled: true,
          mode: 'monitor_only',
          controls: [{ check: 'secrets', stage: 'output', action: 'redact' }],
        },
      );

      const { status, frames } = await askWithPinnedAnswer(
        json,
        agentId,
        'summarise the deployment runbook',
        payload.content,
      );
      expect(status).toBe(200);

      // Nothing user-visible changes. Note this is asserted on the
      // REASSEMBLED answer, not on delta boundaries: the guard still buffers
      // a lookback window in monitor mode, so the deltas are re-cut even
      // though not one character is altered.
      expect(
        answerText(frames),
        'monitor_only must not alter a single character of the answer',
      ).toBe(payload.content);
      expect(frames.some((f) => f.data?.type === 'error')).toBe(false);
      expect(frames.some((f) => f.data?.type === 'guardrail')).toBe(false);

      const messages = await storedMessages(sub);
      expect(messages).toHaveLength(1);
      expect(
        messages[0].response,
        'monitor_only must persist the unmodified answer',
      ).toBe(payload.content);

      // ...but the evidence is recorded, downgraded to `flag`.
      const events = await guardrailEvents(agentId);
      expect(
        events.length,
        'monitor_only must still journal what it saw — otherwise there is ' +
          'nothing to review before promoting the control to enforcing',
      ).toBeGreaterThanOrEqual(1);
      for (const event of events) {
        expect(
          event.action,
          'every control is downgraded to flag under monitor_only',
        ).toBe('flag');
      }
      expect(events[0]).toMatchObject({
        user_id: sub,
        stage: 'output',
        check_name: 'secrets',
        detector_type: 'SECRETS',
        outcome: 'triggered',
        category: 'AWS_ACCESS_KEY',
      });
      expect(events[0].match_count).toBeGreaterThanOrEqual(1);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails · audit journal', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('GET /api/guardrails/events returns the caller\'s decisions and /summary aggregates them', async () => {
    const sub = `e2e-gr-events-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'audit',
        {
          enabled: true,
          mode: 'scan_all',
          block_message: 'Blocked by policy: request quota exceeded.',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['zebrafish-protocol'] },
            },
            { check: 'secrets', stage: 'output', action: 'redact' },
          ],
        },
      );

      // Turn 1: trips the input block.
      await askWithPinnedAnswer(
        json,
        agentId,
        'describe the zebrafish-protocol',
        'never reached',
      );
      // Turn 2: trips the output redaction.
      const payload = buildBoundarySplitAnswer(AWS_KEY);
      await askWithPinnedAnswer(
        json,
        agentId,
        'summarise the runbook',
        payload.content,
      );

      const res = await json.get(
        `/api/guardrails/events?agent_id=${encodeURIComponent(agentId)}`,
      );
      expect(res.status()).toBe(200);
      const body = (await res.json()) as {
        success: boolean;
        events: GuardrailEventRow[];
      };
      expect(body.success).toBe(true);
      expect(
        body.events.length,
        `expected both decisions in the journal, got ${JSON.stringify(body.events)}`,
      ).toBeGreaterThanOrEqual(2);

      const blockEvent = body.events.find(
        (e) => e.stage === 'input' && e.check_name === 'denylist',
      );
      expect(blockEvent, 'the input block must be journalled').toBeTruthy();
      expect(blockEvent).toMatchObject({
        action: 'block',
        outcome: 'triggered',
        category: 'BANNED_TERM',
        detector_type: 'DENYLIST',
      });

      const redactEvent = body.events.find(
        (e) => e.stage === 'output' && e.check_name === 'secrets',
      );
      expect(redactEvent, 'the output redaction must be journalled').toBeTruthy();
      expect(redactEvent).toMatchObject({
        action: 'redact',
        outcome: 'triggered',
        category: 'AWS_ACCESS_KEY',
      });

      for (const event of body.events) {
        expect(event.agent_id).toBe(agentId);
        // The journal must not become the leak channel the checks exist to
        // close: the endpoint projects a public column set, so the scanned
        // text, the owning user id, and the agent's api_key never ship to a
        // client. (`GuardrailEventsRepository._PUBLIC_COLUMNS`.)
        const keys = Object.keys(event as unknown as Record<string, unknown>);
        for (const forbidden of ['matched_value', 'api_key', 'user_id']) {
          expect(
            keys,
            `/api/guardrails/events must not expose ${forbidden}`,
          ).not.toContain(forbidden);
        }
      }

      // The API view and the table must agree on row count, and every row in
      // the table must belong to this caller.
      const dbRows = await guardrailEvents(agentId);
      expect(dbRows.length).toBe(body.events.length);
      for (const row of dbRows) {
        expect(row.user_id).toBe(sub);
      }

      const summaryRes = await json.get('/api/guardrails/summary');
      expect(summaryRes.status()).toBe(200);
      const summary = (await summaryRes.json()) as {
        success: boolean;
        totals: {
          blocked: number;
          flagged: number;
          redacted: number;
          not_evaluated: number;
        };
        breakdown: Array<Record<string, unknown>>;
      };
      expect(summary.success).toBe(true);
      expect(
        summary.totals.blocked,
        'the summary must count the block — this is the number an operator ' +
          'watches when deciding whether a control is too aggressive',
      ).toBeGreaterThanOrEqual(1);
      expect(summary.totals.redacted).toBeGreaterThanOrEqual(1);
      expect(summary.breakdown.length).toBeGreaterThanOrEqual(2);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('the journal is scoped to the requesting user and the agent they can read', async () => {
    const subA = `e2e-gr-scope-a-${Date.now()}`;
    const subB = `e2e-gr-scope-b-${Date.now()}`;
    const tokenA = signJwt(subA);
    const tokenB = signJwt(subB);
    const jsonA = await authedRequest(playwright, tokenA);
    const jsonB = await authedRequest(playwright, tokenB);
    const multipartA = await multipartAuthedRequest(tokenA);
    try {
      const { id: agentId } = await publishGuardrailAgent(
        jsonA,
        multipartA,
        subA,
        'scoped',
        {
          enabled: true,
          mode: 'scan_all',
          controls: [
            {
              check: 'denylist',
              stage: 'input',
              action: 'block',
              settings: { terms: ['zebrafish-protocol'] },
            },
          ],
        },
      );

      await askWithPinnedAnswer(
        jsonA,
        agentId,
        'the zebrafish-protocol please',
        'never reached',
      );
      expect((await guardrailEvents(agentId)).length).toBe(1);

      // A second user's decision on the same agent, injected directly. It
      // cannot be produced through the API without team sharing, but it is
      // exactly the row the `AND user_id = :user_id` clause in
      // `GuardrailEventsRepository.list_for_agent` exists to hide — another
      // member's blocked prompts are not this caller's to read.
      await pg.query(
        `INSERT INTO guardrail_events
           (user_id, agent_id, stage, check_name, detector_type, action,
            outcome, category, match_count)
         VALUES ($1, CAST($2 AS uuid), 'input', 'denylist', 'DENYLIST',
                 'block', 'triggered', 'BANNED_TERM', 1)`,
        [subB, agentId],
      );

      // Two rows now exist on this agent — one per user.
      expect(await guardrailEvents(agentId)).toHaveLength(2);

      const resA = await jsonA.get(
        `/api/guardrails/events?agent_id=${encodeURIComponent(agentId)}`,
      );
      expect(resA.status()).toBe(200);
      const eventsA = ((await resA.json()) as { events: GuardrailEventRow[] })
        .events;
      // The response projects no `user_id`, so ownership is asserted by
      // count against the table: the owner must see their own row and B's
      // must be filtered out by the `AND user_id = :user_id` clause.
      expect(
        eventsA,
        `the owner must see only their own decision, got ${JSON.stringify(eventsA)}`,
      ).toHaveLength(1);
      expect(eventsA[0].stage).toBe('input');
      expect(eventsA[0].check_name).toBe('denylist');

      // User B does not own the agent and has no grant on it, so the
      // endpoint must not even confirm the agent exists.
      const resB = await jsonB.get(
        `/api/guardrails/events?agent_id=${encodeURIComponent(agentId)}`,
      );
      expect(
        resB.status(),
        "another tenant must not read an agent's guardrail journal",
      ).toBe(404);

      // B's own summary must not surface A's decision either.
      const summaryB = await jsonB.get('/api/guardrails/summary');
      expect(summaryB.status()).toBe(200);
      const bodyB = (await summaryB.json()) as {
        totals: { blocked: number };
      };
      expect(
        bodyB.totals.blocked,
        "user B's summary must not count user A's blocked turn",
      ).toBe(1); // only the row seeded above, which belongs to B
    } finally {
      await jsonA.dispose();
      await jsonB.dispose();
      await multipartA.dispose();
    }
  });

  test('GET /api/guardrails/events requires an agent_id and rejects a non-integer limit', async () => {
    const sub = `e2e-gr-events-args-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'args',
        {
          enabled: true,
          controls: [{ check: 'secrets', stage: 'output', action: 'flag' }],
        },
      );

      const missing = await json.get('/api/guardrails/events');
      expect(missing.status()).toBe(400);
      expect(await missing.text()).toContain('agent_id required');

      const badLimit = await json.get(
        `/api/guardrails/events?agent_id=${agentId}&limit=lots`,
      );
      expect(badLimit.status()).toBe(400);
      expect(await badLimit.text()).toContain('limit/offset must be integers');
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });
});

test.describe('tier-b · guardrails · no-regression control', () => {
  test.beforeEach(async () => {
    await resetDb();
  });

  test('an agent with no guardrails config streams and persists exactly as before', async () => {
    const sub = `e2e-gr-noconfig-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    const multipart = await multipartAuthedRequest(token);
    try {
      // Same content that the guarded agents above redact and block on —
      // an unguarded agent must pass all of it through untouched. This is
      // what proves the guardrail machinery is inert when unconfigured
      // rather than silently mangling every agent on the instance.
      const payload = buildBoundarySplitAnswer(AWS_KEY);
      const { id: agentId } = await publishGuardrailAgent(
        json,
        multipart,
        sub,
        'unguarded',
        {},
      );
      expect(
        (
          await pg.query<{ config: Record<string, unknown> }>(
            'SELECT config FROM agents WHERE id = CAST($1 AS uuid)',
            [agentId],
          )
        ).rows[0].config,
      ).toMatchObject({ guardrails: { enabled: false, controls: [] } });

      const { status, frames, text } = await askWithPinnedAnswer(
        json,
        agentId,
        'summarise the deployment runbook',
        payload.content,
      );
      expect(status).toBe(200);
      expect(answerText(frames)).toBe(payload.content);
      expect(
        text,
        'an unguarded agent must not redact anything',
      ).toContain('AKIA');
      expect(frames.some((f) => f.data?.type === 'error')).toBe(false);
      expect(frames[frames.length - 1].data).toEqual({ type: 'end' });

      const messages = await storedMessages(sub);
      expect(messages).toHaveLength(1);
      expect(messages[0].response).toBe(payload.content);

      expect(
        await countRows('guardrail_events'),
        'a turn on an unconfigured agent must write no audit rows',
      ).toBe(0);
      expect(
        await countRows('token_usage', { sql: 'user_id = $1', params: [sub] }),
      ).toBeGreaterThanOrEqual(1);
    } finally {
      await json.dispose();
      await multipart.dispose();
    }
  });

  test('a plain /stream turn with no agent at all is unaffected by the guardrail wiring', async () => {
    const sub = `e2e-gr-noagent-${Date.now()}`;
    const token = signJwt(sub);
    const json = await authedRequest(playwright, token);
    try {
      const answer = 'DocsGPT is an open-source document assistant.';
      const res = await json.post('/stream', {
        data: {
          question: `what is DocsGPT ${emitDirective(answer)}`,
          history: '[]',
          isNoneDoc: true,
        },
      });
      expect(res.status()).toBe(200);
      const frames = parseSseFrames(await res.text());
      expect(answerText(frames)).toBe(answer);
      expect(frames.some((f) => f.data?.type === 'error')).toBe(false);
      expect(await countRows('guardrail_events')).toBe(0);
    } finally {
      await json.dispose();
    }
  });
});
