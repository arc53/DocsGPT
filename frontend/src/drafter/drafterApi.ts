import apiClient from '../api/client';
import { isQuotaError } from '../conversation/quotaError';
import { readSSEStream } from '../events/eventStreamClient';

/** The drafter's routes (session-only on the server; access tokens get 403). */
export const DRAFTER_ENDPOINTS = {
  CONFIG: '/api/drafter/config',
  STREAM: '/api/drafter/stream',
} as const;

/** What a drafter session fills: the agent form, a prompt, or Insights topics. */
export type DrafterRecipe = 'agent' | 'prompt' | 'topics';

/** `GET /api/drafter/config`: whether the wand shows, and on which model. */
export type DrafterConfig = {
  enabled: boolean;
  model: { id: string; display_name: string } | null;
  reason: 'disabled' | 'no_model' | null;
};

/** One turn the client sends; an assistant turn is a questions/proposal event as JSON. */
export type DrafterMessage = { role: 'user' | 'assistant'; content: string };

export type DrafterOption = { id: string; label: string };

export type DrafterQuestion = {
  id: string;
  text: string;
  note: string | null;
  multi: boolean;
  options: DrafterOption[];
};

export type DrafterErrorCode =
  | 'disabled'
  | 'no_model'
  | 'rate_limited'
  | 'quota'
  | 'invalid_output'
  | 'model_error'
  | 'bad_request';

/** The counts a `reading` status reports ("6 knowledge sources, 11 tools…"). */
export type DrafterCounts = Partial<
  Record<'sources' | 'tools' | 'prompts' | 'models' | 'agents', number>
>;

/** One SSE frame of `POST /api/drafter/stream`. */
export type DrafterEvent =
  | { type: 'status'; step: 'reading'; counts?: DrafterCounts }
  | { type: 'status'; step: 'drafting' }
  | { type: 'message'; text: string }
  | { type: 'questions'; questions: DrafterQuestion[] }
  | { type: 'proposal'; proposal: unknown }
  | { type: 'error'; code: DrafterErrorCode; message?: string }
  | { type: 'end' };

export type DrafterRequest = {
  recipe: DrafterRecipe;
  messages: DrafterMessage[];
  context: object;
};

const ERROR_CODES: DrafterErrorCode[] = [
  'disabled',
  'no_model',
  'rate_limited',
  'quota',
  'invalid_output',
  'model_error',
  'bad_request',
];

/**
 * Read the drafter's config. Any failure (an older server without the route,
 * a network error) reads as disabled, so the wand simply doesn't show.
 *
 * Args:
 *   token: The session token.
 *   signal: Aborts the request.
 *
 * Returns:
 *   The config; `enabled: false` when it can't be read.
 */
export async function getDrafterConfig(
  token: string | null,
  signal?: AbortSignal,
): Promise<DrafterConfig> {
  const disabled: DrafterConfig = {
    enabled: false,
    model: null,
    reason: 'disabled',
  };
  try {
    const response: Response = await apiClient.get(
      DRAFTER_ENDPOINTS.CONFIG,
      token,
      {},
      signal,
    );
    if (!response?.ok) return disabled;
    const data = (await response.json()) as Partial<DrafterConfig>;
    return {
      enabled: data.enabled === true,
      model: data.model ?? null,
      reason: data.reason ?? null,
    };
  } catch {
    return disabled;
  }
}

/** The error code for a refused request that never became a stream. */
function codeForStatus(status: number, body: unknown): DrafterErrorCode {
  if (isQuotaError(body)) return 'quota';
  const code = (body as { code?: unknown } | null)?.code;
  if (typeof code === 'string' && ERROR_CODES.includes(code as never))
    return code as DrafterErrorCode;
  if (status === 429) return 'rate_limited';
  if (status === 400 || status === 422) return 'bad_request';
  if (status === 403 || status === 404) return 'disabled';
  return 'model_error';
}

/** Parse one `data:` payload into an event; null for anything unknown. */
export function parseDrafterEvent(data: string): DrafterEvent | null {
  try {
    const parsed = JSON.parse(data) as { type?: unknown };
    if (!parsed || typeof parsed !== 'object') return null;
    switch (parsed.type) {
      case 'status':
      case 'message':
      case 'questions':
      case 'proposal':
      case 'error':
      case 'end':
        return parsed as DrafterEvent;
      default:
        return null;
    }
  } catch {
    return null;
  }
}

/**
 * Run one drafter turn: POST the whole history and hand each SSE event to
 * `onEvent`. It always ends with an `end` event, after a synthesized `error`
 * when the request was refused or the stream broke off without one. An abort
 * stops it quietly (no error, no end).
 *
 * Args:
 *   request: The recipe, the history and the recipe's context.
 *   token: The session token.
 *   onEvent: Called with every event, in order.
 *   signal: Stops the turn (the panel's Stop).
 */
export async function streamDrafter(
  request: DrafterRequest,
  token: string | null,
  onEvent: (event: DrafterEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let finished = false;
  let failed = false;
  const emit = (event: DrafterEvent) => {
    if (finished) return;
    if (event.type === 'end') finished = true;
    if (event.type === 'error') failed = true;
    onEvent(event);
  };
  const fail = (code: DrafterErrorCode, message?: string) => {
    emit({ type: 'error', code, message });
    emit({ type: 'end' });
  };

  let response: Response;
  try {
    response = await apiClient.post(
      DRAFTER_ENDPOINTS.STREAM,
      request,
      token,
      {},
      signal,
    );
  } catch {
    if (!signal.aborted) fail('model_error');
    return;
  }

  const contentType = (
    response.headers?.get('content-type') ?? ''
  ).toLowerCase();
  if (!response.ok && !contentType.includes('text/event-stream')) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      // No JSON body: the status decides.
    }
    const message = (body as { message?: unknown } | null)?.message;
    fail(
      codeForStatus(response.status, body),
      typeof message === 'string' ? message : undefined,
    );
    return;
  }
  if (!response.body) {
    fail('model_error');
    return;
  }

  try {
    await readSSEStream(
      response.body,
      signal,
      () => undefined,
      (record) => {
        if (record.data === undefined) return;
        const event = parseDrafterEvent(record.data);
        if (event) emit(event);
      },
    );
  } catch {
    if (signal.aborted) return;
  }
  if (signal.aborted) return;
  // The stream broke off before its `end`.
  if (finished) return;
  if (failed) emit({ type: 'end' });
  else fail('model_error');
}
