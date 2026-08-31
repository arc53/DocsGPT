/**
 * Guardrail-specific e2e primitives.
 *
 * Two problems the guardrail specs have that no other spec has:
 *
 * 1. **They must pin the model's exact words.** The normal way to do that is
 *    a hash fixture under `scripts/e2e/mock_llm_fixtures/`, but DocsGPT's
 *    system prompt embeds `Today's date is <YYYY-MM-DD>` — the digest of the
 *    same question changes at midnight, so a committed fixture rots within a
 *    day. Instead the stub honours an in-band directive,
 *    `[[MOCK_LLM_EMIT:<base64url>]]`, embedded in the question (see the
 *    module docstring of `scripts/e2e/mock_llm.py`). `emitDirective` builds
 *    it. Base64 matters: it keeps the secret/PII literal out of the request
 *    itself, so an input-stage control cannot "helpfully" redact it and the
 *    persisted conversation prompt never carries it.
 *
 * 2. **They must land a sensitive value across a stream chunk boundary.**
 *    That is the whole point of `StreamingOutputGuard`'s lookback window
 *    (`application/guardrails/stream.py`): a detector that only ever sees the
 *    about-to-emit prefix would miss a match split over two deltas and leak
 *    the first half. `buildBoundarySplitAnswer` constructs an answer where a
 *    given literal provably straddles one of the stub's chunk boundaries,
 *    and returns the offsets so a spec can assert the straddle rather than
 *    assume it.
 */

import type { APIRequestContext } from '@playwright/test';

import { insertFixtureSource } from './agents.js';

/**
 * Number of SSE deltas the stub splits an answer into. Mirrors
 * `STREAM_CHUNK_COUNT` in `scripts/e2e/mock_llm.py`; if that changes, the
 * boundary maths below changes with it.
 */
export const MOCK_STREAM_CHUNK_COUNT = 5;

/**
 * Encode `content` as a `[[MOCK_LLM_EMIT:...]]` directive. Appending the
 * result to a question makes the mock LLM answer with exactly `content`.
 */
export function emitDirective(content: string): string {
  const b64 = Buffer.from(content, 'utf8')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
  return `[[MOCK_LLM_EMIT:${b64}]]`;
}

/**
 * Chunk boundaries the stub will split `content` on — the character offsets
 * where one SSE delta ends and the next begins. Mirrors
 * `_split_into_chunks` in `scripts/e2e/mock_llm.py`.
 */
export function mockChunkBoundaries(content: string): number[] {
  const n = content.length;
  const size = Math.max(
    1,
    Math.ceil(n / MOCK_STREAM_CHUNK_COUNT),
  );
  const boundaries: number[] = [];
  for (let offset = size; offset < n; offset += size) {
    boundaries.push(offset);
  }
  return boundaries;
}

const FILLER =
  'Routine operational detail recorded during the quarterly review cycle. ';

/** Deterministic filler of exactly `n` characters. */
function filler(n: number): string {
  if (n <= 0) return '';
  return FILLER.repeat(Math.ceil(n / FILLER.length)).slice(0, n);
}

export interface BoundarySplitAnswer {
  /** The full answer text to hand the mock LLM. */
  content: string;
  /** Offset of the sensitive literal inside `content`. */
  start: number;
  /** End offset (exclusive) of the sensitive literal. */
  end: number;
  /** The stub chunk boundary that falls strictly inside the literal. */
  boundary: number;
  /** Every chunk boundary, for assertion messages. */
  boundaries: number[];
}

/**
 * Build an answer of `totalChars` characters in which `secret` straddles a
 * mock-LLM chunk boundary.
 *
 * `totalChars` must be a multiple of `MOCK_STREAM_CHUNK_COUNT` so the stub's
 * `ceil(n / 5)` split lands on exact multiples of `totalChars / 5`; the
 * secret is then centred on the first of those boundaries. The literal is
 * surrounded by spaces so word-boundary-anchored detectors (`\bAKIA…`,
 * `(?<!\w)term(?!\w)`) match it as written.
 *
 * Throws rather than returning a non-straddling payload — a guardrail spec
 * that silently stopped exercising the boundary would still pass while
 * testing nothing.
 */
export function buildBoundarySplitAnswer(
  secret: string,
  totalChars = 600,
): BoundarySplitAnswer {
  if (totalChars % MOCK_STREAM_CHUNK_COUNT !== 0) {
    throw new Error(
      `buildBoundarySplitAnswer: totalChars must be a multiple of ` +
        `${MOCK_STREAM_CHUNK_COUNT}, got ${totalChars}`,
    );
  }
  const chunk = totalChars / MOCK_STREAM_CHUNK_COUNT;
  const boundary = chunk;
  const start = boundary - Math.floor(secret.length / 2);
  const end = start + secret.length;
  if (start <= 1 || end >= totalChars - 1) {
    throw new Error(
      `buildBoundarySplitAnswer: secret of length ${secret.length} does not ` +
        `fit around boundary ${boundary} of a ${totalChars}-char answer`,
    );
  }

  // A space immediately before and after the literal so `\b`-anchored
  // detectors see it as a standalone token.
  const head = `${filler(start - 1)} `;
  const tail = ` ${filler(totalChars - end - 1)}`;
  const content = head + secret + tail;

  const boundaries = mockChunkBoundaries(content);
  if (content.length !== totalChars) {
    throw new Error(
      `buildBoundarySplitAnswer: built ${content.length} chars, wanted ${totalChars}`,
    );
  }
  if (content.indexOf(secret) !== start) {
    throw new Error(
      `buildBoundarySplitAnswer: secret landed at ${content.indexOf(secret)}, wanted ${start}`,
    );
  }
  if (!boundaries.some((b) => b > start && b < end)) {
    throw new Error(
      `buildBoundarySplitAnswer: secret [${start},${end}) does not straddle ` +
        `any boundary in [${boundaries.join(', ')}]`,
    );
  }
  return { content, start, end, boundary, boundaries };
}

/**
 * The normalized `guardrails` block as `AgentConfig.model_dump(mode="json")`
 * renders it — i.e. what `agents.config` holds after a successful write.
 */
export interface GuardrailControlPayload {
  check: string;
  stage: string;
  action?: string;
  enabled?: boolean;
  settings?: Record<string, unknown>;
}

export interface GuardrailsConfigPayload {
  enabled?: boolean;
  mode?: string;
  fail_open?: boolean;
  timeout_ms?: number;
  block_message?: string;
  controls?: GuardrailControlPayload[];
}

/**
 * Publish a classic agent whose `config` carries `guardrails`.
 *
 * Published (not draft) on purpose: `StreamProcessor._configure_agent` only
 * loads `agents.config` when the agent resolves to an API key, and a draft
 * row has `key = NULL` — so guardrails configured on a draft never reach the
 * engine. See the note in `guardrails-runtime.spec.ts`.
 *
 * The `sources` row is inserted directly rather than driven through
 * /api/upload: publishing a classic agent requires *a* source, but these
 * specs never retrieve from it (they pass `isNoneDoc`), so paying for Celery
 * ingestion and a Faiss index would buy nothing. Same deviation, and same
 * reasoning, as `helpers/agents.ts::publishClassicAgent`.
 */
export async function publishGuardrailAgent(
  jsonApi: APIRequestContext,
  multipartApi: APIRequestContext,
  userId: string,
  name: string,
  guardrails: GuardrailsConfigPayload,
): Promise<{ id: string; key: string }> {
  const sourceId = await insertFixtureSource(userId, `${name}-src`);

  const promptRes = await jsonApi.post('/api/create_prompt', {
    data: { name: `${name}-prompt`, content: 'Be concise.' },
  });
  if (promptRes.status() !== 200) {
    throw new Error(
      `create_prompt failed ${promptRes.status()}: ${await promptRes.text()}`,
    );
  }
  const { id: promptId } = (await promptRes.json()) as { id: string };

  const createRes = await multipartApi.post('/api/create_agent', {
    multipart: {
      name,
      description: `e2e guardrail agent ${name}`,
      status: 'published',
      agent_type: 'classic',
      chunks: '2',
      retriever: 'classic',
      prompt_id: promptId,
      source: sourceId,
      config: JSON.stringify({ guardrails }),
    },
  });
  if (createRes.status() !== 201) {
    throw new Error(
      `create_agent with guardrails failed ${createRes.status()}: ${await createRes.text()}`,
    );
  }
  const body = (await createRes.json()) as { id: string; key: string };
  if (!body.id || !body.key) {
    throw new Error(`create_agent returned no id/key: ${JSON.stringify(body)}`);
  }
  return body;
}
