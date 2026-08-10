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

/** One `data: <json>` line of an SSE body. */
export interface SseFrame {
  raw: string;
  // The backend emits many distinct payload shapes on one channel.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  data: any;
}

/**
 * Parse an SSE-over-text body into structured frames. Each non-empty
 * `data: <json>` line becomes a frame with a parsed `data` payload. Lines
 * that don't parse as JSON (e.g. `data: [DONE]`) are surfaced with
 * `data = null` and the raw text preserved for the caller.
 */
export function parseSseFrames(text: string): SseFrame[] {
  const frames: SseFrame[] = [];
  for (const line of text.split('\n')) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) continue;
    const payload = trimmed.slice('data:'.length).trim();
    if (!payload) continue;
    try {
      frames.push({ raw: payload, data: JSON.parse(payload) });
    } catch {
      frames.push({ raw: payload, data: null });
    }
  }
  return frames;
}

/**
 * POST /stream, drain the SSE body, and return parsed frames plus the raw
 * text and status. `APIRequestContext` buffers the whole body, so by the
 * time this resolves the server-side generator has emitted its terminal
 * `{"type":"end"}` frame (or errored).
 */
export async function streamFrames(
  api: APIRequestContext,
  body: Record<string, unknown>,
): Promise<{ status: number; frames: SseFrame[]; text: string }> {
  const res = await api.post('/stream', { data: body });
  const text = await res.text();
  return { status: res.status(), frames: parseSseFrames(text), text };
}

/**
 * Concatenate every `{"type":"answer"}` delta in order — the exact text the
 * user ends up seeing in the chat bubble.
 */
export function answerText(frames: SseFrame[]): string {
  return frames
    .filter((f) => f.data?.type === 'answer')
    .map((f) => String(f.data.answer ?? ''))
    .join('');
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
