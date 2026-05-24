/**
 * Shared streaming primitives for SSE specs.
 *
 * The backend exposes two streaming endpoints:
 *   - POST /stream  (answer_ns path="/" + route "/stream") — SSE body
 *   - POST /api/answer — non-streaming one-shot JSON
 *
 * These helpers wrap the SSE-POST-and-drain pattern so specs don't all
 * duplicate the same regex. They return the conversation_id emitted in the
 * final `{type:"id", id:"<uuid>"}` SSE event (see
 * application/api/answer/routes/base.py for the event shape).
 */

import type { APIRequestContext } from '@playwright/test';

/**
 * POST /stream with `body`, drain the SSE payload, and return the
 * `conversation_id` from the trailing `{type:"id", id:"<uuid>"}` event.
 * Throws if the response isn't OK or no id event is present.
 */
export async function streamOnce(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<string> {
  const res = await api.post('/stream', { data: body });
  if (!res.ok()) {
    const text = await res.text().catch(() => '<unreadable>');
    throw new Error(`/stream POST failed ${res.status()}: ${text}`);
  }
  const text = await res.text();
  const match = text.match(/"type"\s*:\s*"id"\s*,\s*"id"\s*:\s*"([^"]+)"/);
  if (!match) {
    throw new Error(`no {type:id} event in SSE payload: ${text}`);
  }
  return match[1];
}

/**
 * Start a /stream POST and return a promise resolving to the HTTP status.
 * For races where the caller wants to kick off a stream and concurrently
 * mutate state without awaiting the SSE drain first.
 */
export function streamInFlight(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<number> {
  return api
    .post('/stream', { data: body })
    .then((r) => r.status())
    .catch(() => 599);
}
