import apiClient from '../api/client';
import endpoints from '../api/endpoints';
import { isQuotaError } from '../conversation/quotaError';
import type { Question, QuestionOption } from '../components/QuestionCards';
import { readSSEStream } from '../events/eventStreamClient';

/**
 * The server's caps on the history a turn sends (docsgpt/drafter/service.py):
 * messages in all, and characters in one user message.
 */
export const DRAFTER_MAX_MESSAGES = 24;
export const DRAFTER_USER_MESSAGE_CHARS = 8000;
/**
 * The longest prompt a turn drafts with (docsgpt/drafter/prompt_recipe.py
 * READ_MAX), for a refusal that doesn't carry its own `limit`.
 */
export const DRAFTER_PROMPT_CHARS = 100_000;

/** What a drafter session fills: the agent form, a prompt, or Insights topics. */
export type DrafterRecipe = 'agent' | 'prompt' | 'topics';

/**
 * `GET /api/drafter/config`: whether the wand shows, and on which model.
 * `unavailable` is the client's own reason: the config couldn't be read.
 */
export type DrafterConfig = {
  enabled: boolean;
  model: { id: string; display_name: string } | null;
  reason: 'disabled' | 'no_model' | 'unavailable' | null;
};

/**
 * One turn the client sends; an assistant turn is a questions/proposal event
 * as JSON (questions carry the line said before them as `message`), or a
 * plain reply's text.
 */
export type DrafterMessage = { role: 'user' | 'assistant'; content: string };

// The shape the chat's `ask_user` questions share (components/QuestionCards).
export type DrafterOption = QuestionOption;

export type DrafterQuestion = Question;

export type DrafterErrorCode =
  | 'disabled'
  | 'no_model'
  | 'rate_limited'
  | 'quota'
  | 'invalid_output'
  | 'model_error'
  /** The task model's provider refused its key: another try fails the same. */
  | 'model_auth'
  /** The server refused the conversation itself (too many or too long messages). */
  | 'bad_request'
  /** The prompt is longer than a turn drafts with (`limit` characters). */
  | 'prompt_too_long'
  /** The message had no text left once cleaned. */
  | 'empty_message'
  /** The request was malformed: nothing the user wrote caused it. */
  | 'request_invalid'
  /** The session ended (HTTP 401): only signing in again helps. */
  | 'auth';

/**
 * The counts a `reading` status reports ("6 knowledge sources, 11 tools…");
 * `insights_conversations` is the analyzed conversations it read from the
 * agent's Insights.
 */
export type DrafterCounts = Partial<
  Record<
    | 'sources'
    | 'tools'
    | 'prompts'
    | 'models'
    | 'agents'
    | 'insights_conversations',
    number
  >
>;

/**
 * One SSE frame of `POST /api/drafter/stream`. `turn` comes first, with the id
 * `cancelDrafterTurn` stops (the request's `turn_id` when the server took it);
 * a server that can't stop turns sends none. A `reading` status without
 * `counts` says the workspace read has started; the one with them follows it.
 */
export type DrafterEvent =
  | { type: 'turn'; id: string }
  | { type: 'status'; step: 'reading'; counts?: DrafterCounts }
  | { type: 'status'; step: 'drafting' }
  | { type: 'message'; text: string }
  /** What a read tool showed the model: end users' questions, as data. */
  | { type: 'read'; kind: 'questions'; items: string[] }
  | { type: 'questions'; questions: DrafterQuestion[] }
  | { type: 'proposal'; proposal: unknown }
  | { type: 'error'; code: DrafterErrorCode; message?: string; limit?: number }
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
  'model_auth',
  'bad_request',
  'prompt_too_long',
  'empty_message',
  'request_invalid',
  'auth',
];

// A refused request's `reason`, as the server names it, to the code the panel
// words it by. Only a refused history (or an older server, which names no
// reason) stays `bad_request`, the one a fresh conversation fixes.
const BAD_REQUEST_REASONS = new Map<unknown, DrafterErrorCode>([
  ['history', 'bad_request'],
  ['too_long', 'prompt_too_long'],
  ['empty', 'empty_message'],
  ['invalid', 'request_invalid'],
]);

/**
 * Read the drafter's config. Any failure (an older server without the route,
 * a network error) reads as off with `reason: 'unavailable'`, so the wand
 * simply doesn't show, and a cache can tell it from a server with drafting
 * off.
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
  const unavailable: DrafterConfig = {
    enabled: false,
    model: null,
    reason: 'unavailable',
  };
  try {
    const response: Response = await apiClient.get(
      endpoints.USER.DRAFTER_CONFIG,
      token,
      {},
      signal,
    );
    if (!response?.ok) return unavailable;
    const data = (await response.json()) as Partial<DrafterConfig>;
    return {
      enabled: data.enabled === true,
      model: data.model ?? null,
      reason: data.reason ?? null,
    };
  } catch {
    return unavailable;
  }
}

/** Why an agent's Insights can't back the drawer's first screen. */
export type AgentGapsReason =
  /** Decision analytics is off on this instance. */
  | 'off_on_this_instance'
  /** The agent's own Insights switch is off. */
  | 'agent_off'
  /** Fewer analyzed conversations than `needed` in the window. */
  | 'not_enough'
  /** Drafting is off. */
  | 'disabled'
  /** The client's own: the summary couldn't be read. */
  | 'unavailable';

/** One (topic, gap type) of an agent's gap summary. */
export type AgentGapRow = {
  /** The topic's name as Insights shows it; null for an agent without topics. */
  topic: string | null;
  /** A `gap_type` option ("docs missing"). */
  gap_type: string;
  /** Expected gaps in the window, rounded. */
  expected: number;
  /** The questions it counts from (the topic's, or every labelled one). */
  turns: number;
  /** The previous window's expected gaps; null until it has labelled answers. */
  previous: number | null;
};

/** `GET /api/drafter/agent_gaps`: what Insights found, for the improve drawer. */
export type AgentGaps = {
  available: boolean;
  reason: AgentGapsReason | null;
  /** Analyzed conversations in the window. */
  conversations: number;
  /** Analyzed conversations it takes (`MIN_SAMPLE`). */
  needed: number;
  /** The window, in days. */
  days: number;
  rows: AgentGapRow[];
};

const isCount = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0;

const GAPS_REASONS: AgentGapsReason[] = [
  'off_on_this_instance',
  'agent_off',
  'not_enough',
  'disabled',
];

/**
 * Read an agent's gap summary (counts only; the server makes no model call).
 * Any failure (an older server, a role that can't edit the agent, a network
 * error) reads as unavailable, so the drawer shows its setup rows alone.
 *
 * Args:
 *   agentId: The saved agent.
 *   token: The session token.
 *   signal: Aborts the request.
 *
 * Returns:
 *   The summary; malformed rows are left out.
 */
export async function getAgentGaps(
  agentId: string,
  token: string | null,
  signal?: AbortSignal,
): Promise<AgentGaps> {
  const unavailable: AgentGaps = {
    available: false,
    reason: 'unavailable',
    conversations: 0,
    needed: 0,
    days: 0,
    rows: [],
  };
  try {
    const response: Response = await apiClient.get(
      endpoints.USER.DRAFTER_AGENT_GAPS(agentId),
      token,
      {},
      signal,
    );
    if (!response?.ok) return unavailable;
    const data = (await response.json()) as Record<string, unknown> | null;
    if (!data || typeof data !== 'object') return unavailable;
    const rows = (Array.isArray(data.rows) ? data.rows : []).filter(
      (row): row is AgentGapRow =>
        !!row &&
        typeof row.gap_type === 'string' &&
        !!row.gap_type &&
        (row.topic === null || typeof row.topic === 'string') &&
        isCount(row.expected) &&
        isCount(row.turns) &&
        (row.previous === null || isCount(row.previous)),
    );
    const reason = GAPS_REASONS.includes(data.reason as AgentGapsReason)
      ? (data.reason as AgentGapsReason)
      : null;
    return {
      available: data.available === true,
      reason: data.available === true ? null : (reason ?? 'unavailable'),
      conversations: isCount(data.conversations) ? data.conversations : 0,
      needed: isCount(data.needed) ? data.needed : 0,
      days: isCount(data.days) ? data.days : 0,
      rows: rows.map(({ topic, gap_type, expected, turns, previous }) => ({
        topic: topic || null,
        gap_type,
        expected,
        turns,
        previous,
      })),
    };
  } catch {
    return unavailable;
  }
}

const isErrorCode = (code: unknown): code is DrafterErrorCode =>
  typeof code === 'string' && ERROR_CODES.includes(code as DrafterErrorCode);

/** A `bad_request`'s code by its `reason`; an unknown reason isn't the history's. */
const badRequestCode = (reason: unknown): DrafterErrorCode =>
  reason === undefined || reason === null
    ? 'bad_request'
    : (BAD_REQUEST_REASONS.get(reason) ?? 'request_invalid');

/** A refusal's `limit`, when it names a usable one. */
const limitOf = (body: unknown): { limit?: number } => {
  const limit = (body as { limit?: unknown } | null)?.limit;
  return typeof limit === 'number' && Number.isFinite(limit) && limit > 0
    ? { limit }
    : {};
};

/** The error code for a refused request that never became a stream. */
function codeForStatus(status: number, body: unknown): DrafterErrorCode {
  if (isQuotaError(body)) return 'quota';
  const { code, reason } = (body ?? {}) as { code?: unknown; reason?: unknown };
  if (code === 'bad_request') return badRequestCode(reason);
  if (isErrorCode(code)) return code;
  if (status === 401) return 'auth';
  if (status === 429) return 'rate_limited';
  if (status === 400 || status === 422) return badRequestCode(reason);
  if (status === 403 || status === 404) return 'disabled';
  return 'model_error';
}

/** Parse one `data:` payload into an event; null for anything unknown. */
export function parseDrafterEvent(data: string): DrafterEvent | null {
  try {
    const parsed = JSON.parse(data) as { type?: unknown; id?: unknown };
    if (!parsed || typeof parsed !== 'object') return null;
    switch (parsed.type) {
      case 'turn':
        return typeof parsed.id === 'string' ? (parsed as DrafterEvent) : null;
      case 'read': {
        const { kind, items } = parsed as { kind?: unknown; items?: unknown };
        if (kind !== 'questions' || !Array.isArray(items)) return null;
        return {
          type: 'read',
          kind,
          items: items.filter(
            (item): item is string => typeof item === 'string' && !!item.trim(),
          ),
        };
      }
      case 'error': {
        // A code this client has no words for reads as a model error; a
        // refused request reads by its reason.
        const { code, message, reason } = parsed as {
          code?: unknown;
          message?: unknown;
          reason?: unknown;
        };
        const read =
          code === 'bad_request'
            ? badRequestCode(reason)
            : isErrorCode(code)
              ? code
              : 'model_error';
        return {
          type: 'error',
          code: read,
          ...(typeof message === 'string' ? { message } : {}),
          ...(read === 'prompt_too_long' ? limitOf(parsed) : {}),
        };
      }
      case 'status':
      case 'message':
      case 'questions':
      case 'proposal':
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
 * A new turn id in the form the server takes: 32 lowercase hex characters.
 * `getRandomValues`, unlike `randomUUID`, also works over plain HTTP.
 */
export function newDrafterTurnId(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');
}

/**
 * Stop a running turn on the server before its next model call. Aborting the
 * stream alone doesn't: the production server finishes a turn whose client
 * went away. Best-effort: a failure (the turn already ended, no Redis) is
 * ignored.
 *
 * Args:
 *   turnId: The id the request sent, or the one its `turn` event carried.
 *   token: The session token.
 */
export async function cancelDrafterTurn(
  turnId: string,
  token: string | null,
): Promise<void> {
  try {
    await apiClient.post(endpoints.USER.DRAFTER_TURN_CANCEL(turnId), {}, token);
  } catch {
    // Nothing to do: the turn runs to its end.
  }
}

/**
 * Run one drafter turn: POST the whole history and hand each SSE event to
 * `onEvent`. It always ends with an `end` event, after a synthesized `error`
 * when the request was refused or the stream broke off without one. A stream
 * that broke off after its questions or proposal only lost its `end`: the turn
 * answered, so it just ends. An abort stops it quietly (no error, no end).
 *
 * Args:
 *   request: The recipe, the history and the recipe's context.
 *   token: The session token.
 *   onEvent: Called with every event, in order.
 *   signal: Stops the turn (the panel's Stop).
 *   turnId: The turn's id (`newDrafterTurnId`), sent as `turn_id` so a Stop
 *     before the `turn` event arrives still reaches it.
 */
export async function streamDrafter(
  request: DrafterRequest,
  token: string | null,
  onEvent: (event: DrafterEvent) => void,
  signal: AbortSignal,
  turnId?: string,
): Promise<void> {
  let finished = false;
  let failed = false;
  // The turn's answer arrived: nothing but `end` comes after it.
  let answered = false;
  const emit = (event: DrafterEvent) => {
    if (finished) return;
    if (event.type === 'end') finished = true;
    if (event.type === 'error') failed = true;
    if (event.type === 'questions' || event.type === 'proposal')
      answered = true;
    onEvent(event);
  };
  const fail = (
    code: DrafterErrorCode,
    message?: string,
    limit?: { limit?: number },
  ) => {
    emit({ type: 'error', code, message, ...limit });
    emit({ type: 'end' });
  };

  let response: Response;
  try {
    response = await apiClient.post(
      endpoints.USER.DRAFTER_STREAM,
      turnId ? { ...request, turn_id: turnId } : request,
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
    const code = codeForStatus(response.status, body);
    fail(
      code,
      typeof message === 'string' ? message : undefined,
      code === 'prompt_too_long' ? limitOf(body) : undefined,
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
  // The stream broke off before its `end`. A turn that only said something
  // fails: its words may have been the start of questions to come.
  if (finished) return;
  if (failed || answered) emit({ type: 'end' });
  else fail('model_error');
}
