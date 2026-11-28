import i18n from 'i18next';

import { baseURL } from '../api/client';
import {
  reportWorkspaceRefusal,
  requestWorkspace,
} from '../workspace/requestWorkspace';
import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import {
  Answer,
  ClientCapability,
  FEEDBACK,
  RetrievalPayload,
} from './conversationModels';
import { noteQuotaError, noteTurnFinished } from '../payer/usageSlice';
import {
  agentLimitErrorMessage,
  isAgentLimitError,
  isQuotaError,
  PAYER_STOP_CODES,
  QUOTA_EXCEEDED,
  quotaErrorMessage,
  quotaErrorParams,
} from './quotaError';
import { ToolCallsType } from './types';
import { CONNECTION_LOST } from './curatedError';

/**
 * Mirrors the backend's ``_SEQUENCE_NO_RE`` (application/api/answer/
 * routes/messages.py) — only non-negative decimal integers are valid
 * cursors. Rejects empty strings (Number("") === 0), hex literals,
 * exponential notation, and anything else that ``Number(...)`` would
 * happily coerce.
 */
const _SEQUENCE_NO_RE = /^\d+$/;

/** Chat refusals about the workspace, which the chat words and can fix. */
const WORKSPACE_ERROR_CODES: ReadonlySet<string> = new Set([
  'workspace_mismatch',
  'workspace_not_found',
]);

/**
 * Tells the usage slice a turn ended, from its terminal stream frame: a stop
 * for the person's allowance reads the quota at once, any other end after a
 * pause (the turn's spend may have moved the meter).
 */
function _noteUsage(frame: { type?: unknown; code?: unknown }): void {
  if (frame.type === 'error' && frame.code === QUOTA_EXCEEDED) noteQuotaError();
  else if (frame.type === 'end' || frame.type === 'error') noteTurnFinished();
}

/**
 * Drain an SSE response body, forwarding each ``data:`` line to
 * ``onData`` and tracking the most recent ``id:`` header. Returns
 * when the body ends, the signal aborts, or ``shouldStop()`` returns
 * true (e.g. a terminal ``end``/``error`` event was dispatched —
 * the reconnect endpoint is a live tail that doesn't close on its
 * own past terminal replay).
 */
/**
 * Convert a non-SSE pre-stream HTTP failure (e.g. ``check_usage``'s
 * 429 JSON response) into a synthetic typed ``error`` frame so the
 * caller's slice sees the actual server message instead of the
 * generic "Connection lost" synthesised when the drainer finishes
 * with zero events. Returns true if a frame was dispatched and the
 * caller should skip ``_drainSseBody`` entirely.
 *
 * SSE-shaped error bodies (``mimetype="text/event-stream"``) are
 * left alone — the drainer parses the typed ``error`` frame they
 * carry through the normal path.
 */
async function _handlePreStreamHttpError(
  response: Response,
  dispatch: (data: string) => void,
): Promise<boolean> {
  if (response.ok) return false;
  const contentType = (
    response.headers.get('content-type') ?? ''
  ).toLowerCase();
  if (contentType.includes('text/event-stream')) return false;
  let message: string | null = null;
  let code: string | null = null;
  let params: Record<string, unknown> | null = null;
  try {
    const text = await response.text();
    if (text) {
      try {
        const parsed = JSON.parse(text);
        if (isQuotaError(parsed)) {
          message = quotaErrorMessage(parsed, i18n.t.bind(i18n), i18n.language);
          // With its code and values the chat words it as the in-run stop is.
          code = QUOTA_EXCEEDED;
          params = quotaErrorParams(parsed);
        } else if (
          parsed &&
          typeof parsed === 'object' &&
          PAYER_STOP_CODES.has(parsed.error_code)
        ) {
          // The agent is paused or has nobody to pay for it: no numbers.
          code = parsed.error_code;
          message =
            (typeof parsed.message === 'string' && parsed.message) || code;
        } else if (isAgentLimitError(parsed)) {
          // The agent's own limit, worded for the user: a code makes the
          // chat show it as prose rather than a raw server error.
          message = agentLimitErrorMessage(
            parsed,
            i18n.t.bind(i18n),
            i18n.language,
          );
          code = 'agent-limit-exceeded';
        } else if (parsed && typeof parsed === 'object') {
          // A workspace refusal keeps its code, so the chat can word it and
          // offer the fix.
          if (
            typeof parsed.error === 'string' &&
            WORKSPACE_ERROR_CODES.has(parsed.error)
          )
            code = parsed.error;
          message =
            (typeof parsed.message === 'string' && parsed.message) ||
            (typeof parsed.error === 'string' && parsed.error) ||
            (typeof parsed.detail === 'string' && parsed.detail) ||
            null;
        }
      } catch {
        message = text.slice(0, 500);
      }
    }
  } catch {
    // Body already consumed or unreadable — fall through to the
    // status-line fallback below.
  }
  if (!message) {
    message = `HTTP ${response.status} ${response.statusText}`.trim();
  }
  dispatch(
    JSON.stringify(
      code
        ? { type: 'error', error: message, code, ...(params && { params }) }
        : { type: 'error', error: message },
    ),
  );
  return true;
}

/**
 * Passes a refused stream's ``error`` code to the workspace checks, as the
 * API client does for a JSON refusal (a 404 ``workspace_not_found`` reloads
 * the caller's workspaces).
 *
 * Args:
 *   status: The response's HTTP status.
 *   data: One ``data:`` payload of the stream.
 *   workspace: The workspace the request was sent for.
 */
function _reportStreamRefusal(
  status: number,
  data: string,
  workspace: string,
): void {
  try {
    const parsed = JSON.parse(data);
    if (parsed?.type === 'error' && typeof parsed.code === 'string')
      reportWorkspaceRefusal(status, parsed.code, workspace);
  } catch {
    // Not JSON: nothing to report.
  }
}

async function _drainSseBody(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  onData: (data: string) => void,
  onId: (id: number) => void,
  shouldStop?: () => boolean,
  onActivity?: () => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let stoppedEarly = false;
  try {
    while (true) {
      if (signal.aborted) break;
      if (shouldStop?.()) {
        stoppedEarly = true;
        break;
      }
      const { done, value } = await reader.read();
      if (done) break;
      // Any bytes count, keepalive comments included: the idle watchdog
      // only has to tell a live stream from a dead socket.
      onActivity?.();
      buffer += decoder.decode(value, { stream: true });
      // Normalise mixed line terminators so a stray CR can't smuggle
      // a record boundary inside a JSON payload.
      buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      let boundary = buffer.indexOf('\n\n');
      while (boundary !== -1) {
        const record = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        boundary = buffer.indexOf('\n\n');
        if (record.length === 0) continue;
        const dataParts: string[] = [];
        let sawDataField = false;
        for (const line of record.split('\n')) {
          if (line.length === 0) continue;
          if (line.startsWith(':')) continue; // SSE comment / keepalive
          const colonIdx = line.indexOf(':');
          const field = colonIdx === -1 ? line : line.slice(0, colonIdx);
          let value = colonIdx === -1 ? '' : line.slice(colonIdx + 1);
          if (value.startsWith(' ')) value = value.slice(1);
          if (field === 'id') {
            // Strict regex match — empty value, hex, ``-1`` (the
            // backend's terminal snapshot-failure synthetic), and
            // exponent forms are all rejected so they can't silently
            // rewrite the reconnect cursor.
            if (_SEQUENCE_NO_RE.test(value)) onId(parseInt(value, 10));
          } else if (field === 'data') {
            sawDataField = true;
            dataParts.push(value);
          }
        }
        if (!sawDataField) continue;
        const data = dataParts.join('\n').trim();
        if (data.length === 0) continue;
        onData(data);
        if (shouldStop?.()) {
          stoppedEarly = true;
          break;
        }
      }
      if (stoppedEarly) break;
    }
  } finally {
    if (stoppedEarly) {
      // Ask the runtime to tear the underlying response body down so
      // the server-side WSGI thread isn't pinned waiting on
      // keepalives. ``releaseLock`` alone leaves the body half-open.
      try {
        await reader.cancel();
      } catch {
        // Already errored / closed.
      }
    }
    try {
      reader.releaseLock();
    } catch {
      // Already released.
    }
  }
}

/** Delays before each attempt to resume a dropped chat stream; the first is immediate. */
const RESUME_BACKOFF_MS = [0, 1_000, 2_000, 4_000, 8_000, 15_000];
/** Attempts in a row that deliver nothing before the client stops resuming. */
const RESUME_MAX_ATTEMPTS = 8;
/** How long one attempt waits for the browser to come back online. */
const RESUME_OFFLINE_WAIT_MS = 60_000;
/**
 * Silence after which a chat stream counts as dead. The server writes a
 * keepalive every 15 s (``SSE_KEEPALIVE_SECONDS``), so this is three missed
 * ones. A socket that died without a FIN or RST (a phone that changed
 * network, a laptop that slept) never errors on its own.
 */
export const STREAM_IDLE_TIMEOUT_MS = 45_000;

function _withJitter(delayMs: number): number {
  return delayMs + Math.random() * delayMs * 0.2;
}

/**
 * An abort signal that follows ``parent`` and also fires after ``idleMs``
 * without ``heard()``. The timer starts at the first ``heard()`` unless
 * ``armed`` is set, so a request still waiting for its response headers is
 * not cut.
 */
function _idleWatchdog(
  parent: AbortSignal,
  idleMs: number,
  armed = false,
): { signal: AbortSignal; heard: () => void; stop: () => void } {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (parent.aborted) controller.abort();
  else parent.addEventListener('abort', abort, { once: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const heard = () => {
    clearTimeout(timer);
    timer = setTimeout(abort, idleMs);
  };
  if (armed) heard();
  return {
    signal: controller.signal,
    heard,
    stop: () => {
      clearTimeout(timer);
      parent.removeEventListener('abort', abort);
    },
  };
}

/**
 * Resolves after ``ms``, or once ``signal`` aborts, or when the browser comes
 * back online (no point waiting out a backoff once the network is back).
 */
function _pause(ms: number, signal: AbortSignal): Promise<void> {
  if (ms <= 0 || signal.aborted) return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      window.removeEventListener('online', done);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, ms);
    window.addEventListener('online', done);
    signal.addEventListener('abort', done, { once: true });
  });
}

/** Resolves once the browser is online, after ``maxMs`` at most, or when ``signal`` aborts. */
function _waitUntilOnline(signal: AbortSignal, maxMs: number): Promise<void> {
  if (signal.aborted || typeof navigator === 'undefined' || navigator.onLine)
    return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      clearTimeout(timer);
      window.removeEventListener('online', done);
      signal.removeEventListener('abort', done);
      resolve();
    };
    const timer = setTimeout(done, maxMs);
    window.addEventListener('online', done);
    signal.addEventListener('abort', done, { once: true });
  });
}

/**
 * Follow a chat answer whose stream dropped, through the journal replay at
 * ``GET /api/messages/<id>/events``, until a terminal frame arrives.
 *
 * The answer keeps running on the server when the client's connection drops,
 * so the stream is retried with backoff, waiting for the browser to come back
 * online, and with an idle watchdog on each attempt. An attempt that delivered
 * events resets the backoff; ``429`` (the per-user connection cap, held by
 * connections that died with the network) and ``5xx`` are retried.
 *
 * Args:
 *   opts.messageId: The answer's message id (from the ``message_id`` frame).
 *   opts.token: Bearer token, or null without auth.
 *   opts.signal: The caller's abort signal (Stop, navigation).
 *   opts.dispatch: Receives each ``data`` payload, as the live stream's did.
 *   opts.lastEventId: The cursor of the last event received.
 *   opts.onId: Receives each new cursor.
 *   opts.isDone: True once a terminal frame was dispatched.
 *
 * Returns:
 *   ``ended`` when a terminal frame arrived (or the caller aborted),
 *   ``gone`` when the server no longer has the message for this caller
 *   (401, 403, 404), and ``gave_up`` after ``RESUME_MAX_ATTEMPTS`` attempts
 *   in a row delivered nothing.
 */
async function _resumeMessageStream(opts: {
  messageId: string;
  token: string | null;
  signal: AbortSignal;
  dispatch: (data: string) => void;
  lastEventId: () => number | null;
  onId: (id: number) => void;
  isDone: () => boolean;
}): Promise<'ended' | 'gone' | 'gave_up'> {
  const { signal } = opts;
  let failures = 0;
  while (failures < RESUME_MAX_ATTEMPTS) {
    const backoff =
      RESUME_BACKOFF_MS[Math.min(failures, RESUME_BACKOFF_MS.length - 1)];
    await _pause(_withJitter(backoff), signal);
    await _waitUntilOnline(signal, RESUME_OFFLINE_WAIT_MS);
    if (signal.aborted || opts.isDone()) return 'ended';

    const url = new URL(`${baseURL}/api/messages/${opts.messageId}/events`);
    const cursor = opts.lastEventId();
    if (cursor !== null) url.searchParams.set('last_event_id', String(cursor));
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (opts.token) headers.Authorization = `Bearer ${opts.token}`;

    // Armed at once: the reconnect endpoint answers right away, and a
    // request sent into a dead network may otherwise hang for minutes.
    const watchdog = _idleWatchdog(signal, STREAM_IDLE_TIMEOUT_MS, true);
    let progressed = false;
    try {
      const response = await fetch(url.toString(), {
        method: 'GET',
        headers,
        signal: watchdog.signal,
        cache: 'no-store',
      });
      watchdog.heard();
      if ([401, 403, 404].includes(response.status)) return 'gone';
      if (response.ok && response.body) {
        await _drainSseBody(
          response.body,
          watchdog.signal,
          (data) => {
            progressed = true;
            opts.dispatch(data);
          },
          opts.onId,
          opts.isDone,
          watchdog.heard,
        );
      } else {
        console.warn(
          `Stream resume: HTTP ${response.status} ${response.statusText}`,
        );
      }
    } catch (err) {
      console.warn('Stream resume attempt failed:', err);
    } finally {
      watchdog.stop();
    }
    if (signal.aborted || opts.isDone()) return 'ended';
    failures = progressed ? 0 : failures + 1;
  }
  return 'gave_up';
}

/**
 * Puts the composer's knowledge on a request: the picked sources as
 * ``active_docs`` (one id, or a list for several) with the first one's
 * retriever, and whole folders as ``active_folders``, which the server reads
 * live (an agent chat ignores them, as it does the sources).
 *
 * Args:
 *   payload: The request, changed in place.
 *   selectedDocs: The picked sources.
 *   activeFolders: The picked folder ids.
 */
export function applySelectedKnowledge(
  payload: RetrievalPayload,
  selectedDocs: Doc[],
  activeFolders: string[] = [],
): void {
  if (selectedDocs.length > 1) {
    payload.active_docs = selectedDocs.map((doc) => doc.id!);
    payload.retriever = selectedDocs[0]?.retriever as string;
  } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
    // One source goes as a plain id (backward compatibility).
    payload.active_docs = selectedDocs[0].id as string;
    payload.retriever = selectedDocs[0].retriever as string;
  }
  if (activeFolders.length > 0) payload.active_folders = activeFolders;
}

/**
 * What the web app can render, sent with every ``/stream`` request. ``forms``:
 * it draws clarifying questions as cards and resumes the turn with the
 * answer; without it the server never offers the model questions.
 */
export const CLIENT_CAPABILITIES: ClientCapability[] = ['forms'];

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc[],
  conversationId: string | null,
  promptId: string | null,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  idempotencyKey?: string,
  activeFolders: string[] = [],
): Promise<
  | {
      result: any;
      answer: any;
      thought: any;
      sources: any;
      toolCalls: ToolCallsType[];
      conversationId: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      thought: any;
      sources: any;
      toolCalls: ToolCallsType[];
      query: string;
      conversationId: any;
      title: any;
    }
> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    isNoneDoc: selectedDocs.length === 0 && activeFolders.length === 0,
    agent_id: agentId,
    save_conversation: save_conversation,
    // The backend persists every conversation hidden unless the request
    // explicitly opts into the sidebar; save_conversation alone no longer
    // lists it.
    visibility: save_conversation ? 'listed' : 'hidden',
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  applySelectedKnowledge(payload, selectedDocs, activeFolders);
  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;
  return conversationService
    .answer(payload, token, signal, headers)
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        return Promise.reject(new Error(response.statusText));
      }
    })
    .then((data) => {
      const result = data.answer;
      return {
        answer: result,
        query: question,
        result,
        thought: data.thought,
        sources: data.sources,
        toolCalls: data.tool_calls,
        conversationId: data.conversation_id,
        title: data.title || null,
      };
    });
}

export function handleFetchAnswerSteaming(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc[],
  conversationId: string | null,
  promptId: string | null,
  onEvent: (event: MessageEvent) => void,
  indx?: number,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  idempotencyKey?: string,
  activeFolders: string[] = [],
): Promise<Answer> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    isNoneDoc: selectedDocs.length === 0 && activeFolders.length === 0,
    index: indx,
    agent_id: agentId,
    save_conversation: save_conversation,
    // The backend persists every conversation hidden unless the request
    // explicitly opts into the sidebar; save_conversation alone no longer
    // lists it.
    visibility: save_conversation ? 'listed' : 'hidden',
    capabilities: CLIENT_CAPABILITIES,
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  applySelectedKnowledge(payload, selectedDocs, activeFolders);

  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

  // Per-stream state used for reconnect-after-disconnect.
  let messageId: string | null = null;
  let lastEventId: number | null = null;
  // The single JSON.parse below feeds both the message_id capture and
  // the termination flag — cheaper and stricter than substring
  // matching the wire bytes.
  let endReceived = false;

  const dispatch = (data: string) => {
    try {
      const parsed = JSON.parse(data);
      if (parsed && typeof parsed === 'object') {
        if (parsed.type === 'message_id' && parsed.message_id) {
          messageId = parsed.message_id;
        } else if (parsed.type === 'end' || parsed.type === 'error') {
          if (!endReceived) _noteUsage(parsed);
          endReceived = true;
        }
      }
    } catch {
      // Not JSON — pass through anyway; the caller handles raw lines.
    }
    onEvent(new MessageEvent('message', { data }));
  };

  const runInitialPost = async (): Promise<void> => {
    // The workspace a new chat is started in, as the request names it.
    const workspace = requestWorkspace();
    // Cuts a stream gone silent (a dead socket never errors), so the
    // resume below can take over. Armed once the response arrives.
    const watchdog = _idleWatchdog(signal, STREAM_IDLE_TIMEOUT_MS);
    try {
      await runInitialPostWith(workspace, watchdog);
    } finally {
      watchdog.stop();
    }
  };

  const runInitialPostWith = async (
    workspace: string,
    watchdog: ReturnType<typeof _idleWatchdog>,
  ): Promise<void> => {
    const response = await conversationService.answerStream(
      payload,
      token,
      watchdog.signal,
      headers,
    );
    watchdog.heard();
    // Pre-stream HTTP failures with non-SSE bodies (e.g. ``check_usage``
    // returning a JSON 429) drain as zero events and would otherwise
    // be masked by the generic "Connection lost" synthetic. Convert
    // them into a typed ``error`` frame so the real message surfaces.
    if (await _handlePreStreamHttpError(response, dispatch)) return;
    if (!response.body) throw new Error('No response body');
    // A refusal sent as an event stream: the API client checks only JSON
    // bodies for a team the caller is no longer in, so it is told here.
    const refusal = response.ok ? null : response.status;
    await _drainSseBody(
      response.body,
      watchdog.signal,
      (data) => {
        if (refusal !== null) _reportStreamRefusal(refusal, data, workspace);
        dispatch(data);
      },
      (id) => {
        lastEventId = id;
      },
      undefined,
      watchdog.heard,
    );
  };

  const resume = (): Promise<'ended' | 'gone' | 'gave_up'> =>
    _resumeMessageStream({
      messageId: messageId as string,
      token,
      signal,
      dispatch,
      lastEventId: () => lastEventId,
      onId: (id) => {
        lastEventId = id;
      },
      isDone: () => endReceived,
    });

  return new Promise<Answer>((resolve, reject) => {
    (async () => {
      try {
        try {
          await runInitialPost();
        } catch (initialErr) {
          // Mid-stream network failures (WiFi blip, worker recycle,
          // body reader rejecting) surface as a thrown error — not a
          // graceful EOF. If the stream had already started (we have a
          // ``messageId``), fall through to the reconnect path so the
          // journal-backed replay can finish what the live socket
          // couldn't. Pre-stream failures (auth, DNS, server 4xx/5xx
          // before any yield) lack a messageId and bubble up.
          if (signal.aborted || !messageId) throw initialErr;
          console.warn(
            'Initial stream failed mid-flight, attempting reconnect:',
            initialErr,
          );
        }
        // The backend ends the stream cleanly with a typed ``end``
        // event. Anything else (network drop, worker recycle, a socket
        // gone silent) is a premature close: the answer is still running
        // on the server, so follow it through the journal replay.
        if (!endReceived && !signal.aborted && messageId) {
          await resume();
        }
        // No terminal frame: synthesize one through the same ``dispatch``
        // path the wire events use, or the slice never leaves
        // ``streaming``. The code and message id let the slice keep
        // following the answer (the server may still finish it) instead of
        // failing the turn.
        if (!endReceived && !signal.aborted) {
          dispatch(
            JSON.stringify({
              type: 'error',
              error:
                'Connection lost. The response could not be resumed; please try again.',
              code: CONNECTION_LOST,
              ...(messageId ? { message_id: messageId } : {}),
            }),
          );
        }
        // The handler historically never explicitly resolved with a
        // value — callers consume the streamed events via ``onEvent``
        // and read final state from Redux. Preserve that contract.
        resolve(undefined as unknown as Answer);
      } catch (error) {
        if (signal.aborted) {
          resolve(undefined as unknown as Answer);
          return;
        }
        console.error('Connection failed:', error);
        reject(error);
      }
    })();
  });
}

/**
 * One action on a paused call: an approval's decision, a client tool's
 * result, or a clarifying question's answer (or ``skipped``).
 */
export type ToolAction = {
  call_id: string;
  decision?: 'approved' | 'denied';
  comment?: string;
  result?: Record<string, any>;
  answer?: string;
  skipped?: true;
};

export function handleSubmitToolActions(
  conversationId: string,
  toolActions: ToolAction[],
  token: string | null,
  signal: AbortSignal,
  onEvent: (event: MessageEvent) => void,
  idempotencyKey?: string,
): Promise<Answer> {
  const payload = {
    conversation_id: conversationId,
    tool_actions: toolActions,
    capabilities: CLIENT_CAPABILITIES,
  };

  const headers: Record<string, string> = {};
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey;

  // Tool-action submissions resume against the original
  // ``reserved_message_id``, so the backend's continuation path emits
  // ``id:`` prefixed records that the legacy parser would silently
  // drop. Use the shared SSE drainer — and the same reconnect-on-
  // premature-close pattern as ``handleFetchAnswerSteaming`` so a
  // dropped tool-action stream can pick up after the disconnect.
  let messageId: string | null = null;
  let lastEventId: number | null = null;

  // Track whether the typed ``end`` event was observed. The single
  // JSON.parse below feeds both the message_id capture and the
  // termination flag — cheaper and stricter than substring matching
  // the wire bytes.
  let endReceived = false;

  const dispatch = (data: string) => {
    try {
      const parsed = JSON.parse(data);
      if (parsed && typeof parsed === 'object') {
        if (parsed.type === 'message_id' && parsed.message_id) {
          messageId = parsed.message_id;
        } else if (parsed.type === 'end' || parsed.type === 'error') {
          // Match the backend's terminal set in
          // ``application/streaming/event_replay.py``: the agent's
          // catch-all path emits ``error`` *without* a trailing
          // ``end``, so treating only ``end`` as terminal would
          // trigger a reconnect against an already-finished stream
          // and hang on keepalives.
          if (!endReceived) _noteUsage(parsed);
          endReceived = true;
        }
      }
    } catch {
      // Not JSON — pass through anyway; the caller handles raw lines.
    }
    onEvent(new MessageEvent('message', { data }));
  };

  const runInitial = async (): Promise<void> => {
    // Same idle watchdog as ``handleFetchAnswerSteaming``.
    const watchdog = _idleWatchdog(signal, STREAM_IDLE_TIMEOUT_MS);
    try {
      const response = await conversationService.answerStream(
        payload,
        token,
        watchdog.signal,
        headers,
      );
      watchdog.heard();
      // See ``handleFetchAnswerSteaming`` for the rationale: non-SSE
      // HTTP failures (e.g. ``check_usage`` 429 JSON) need to be lifted
      // into a typed ``error`` frame before they reach the drainer.
      if (await _handlePreStreamHttpError(response, dispatch)) return;
      if (!response.body) throw new Error('No response body');
      await _drainSseBody(
        response.body,
        watchdog.signal,
        dispatch,
        (id) => {
          lastEventId = id;
        },
        undefined,
        watchdog.heard,
      );
    } finally {
      watchdog.stop();
    }
  };

  const resume = (): Promise<'ended' | 'gone' | 'gave_up'> =>
    _resumeMessageStream({
      messageId: messageId as string,
      token,
      signal,
      dispatch,
      lastEventId: () => lastEventId,
      onId: (id) => {
        lastEventId = id;
      },
      isDone: () => endReceived,
    });

  return new Promise<Answer>((resolve, reject) => {
    (async () => {
      try {
        try {
          await runInitial();
        } catch (initialErr) {
          // Same premature-close handling as
          // ``handleFetchAnswerSteaming``: a thrown reader error after
          // the message_id frame still warrants one reconnect attempt
          // against the journal. Pre-stream failures lack a messageId
          // and bubble up.
          if (signal.aborted || !messageId) throw initialErr;
          console.warn(
            'Tool-actions stream failed mid-flight, attempting reconnect:',
            initialErr,
          );
        }
        if (!endReceived && !signal.aborted && messageId) {
          await resume();
        }
        // Synthesize a terminal error if reconnect couldn't deliver one
        // (4xx/5xx, network drop, silent live tail). Same reasoning as
        // ``handleFetchAnswerSteaming``: the caller's slice only exits
        // the streaming state on a terminal frame.
        if (!endReceived && !signal.aborted) {
          dispatch(
            JSON.stringify({
              type: 'error',
              error:
                'Connection lost. The tool response could not be resumed; please try again.',
              code: CONNECTION_LOST,
              ...(messageId ? { message_id: messageId } : {}),
            }),
          );
        }
        resolve(undefined as unknown as Answer);
      } catch (error) {
        if (signal.aborted) {
          resolve(undefined as unknown as Answer);
          return;
        }
        console.error('Tool actions submission failed:', error);
        reject(error);
      }
    })();
  });
}

/**
 * Stream a chat completion via the /v1/chat/completions endpoint.
 *
 * Translates the standard streaming format (choices[0].delta) back into
 * the internal DocsGPT event shape so the existing Redux reducers can
 * consume the events without any changes.
 */
export function handleV1ChatCompletionStreaming(
  question: string,
  signal: AbortSignal,
  agentApiKey: string,
  history: { prompt: string; response: string }[],
  onEvent: (event: MessageEvent) => void,
  tools?: any[],
  attachments?: string[],
): Promise<Answer> {
  // Build messages array from history + current question
  const messages: any[] = [];
  for (const h of history) {
    messages.push({ role: 'user', content: h.prompt });
    messages.push({ role: 'assistant', content: h.response });
  }
  messages.push({ role: 'user', content: question });

  const payload: any = {
    messages,
    stream: true,
  };
  if (tools && tools.length > 0) {
    payload.tools = tools;
  }
  if (attachments && attachments.length > 0) {
    payload.docsgpt = { attachments };
  }

  return new Promise<Answer>((resolve, reject) => {
    conversationService
      .chatCompletions(payload, agentApiKey, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        let buffer = '';
        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');

        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) return;

          const chunk = decoder.decode(value);
          buffer += chunk;

          const events = buffer.split('\n\n');
          buffer = events.pop() ?? '';

          for (const event of events) {
            if (!event.trim().startsWith('data:')) continue;

            const dataLine = event
              .split('\n')
              .map((line: string) => line.replace(/^data:\s?/, ''))
              .join('');

            const trimmed = dataLine.trim();

            // Handle [DONE] sentinel
            if (trimmed === '[DONE]') {
              onEvent(
                new MessageEvent('message', {
                  data: JSON.stringify({ type: 'end' }),
                }),
              );
              continue;
            }

            try {
              const parsed = JSON.parse(trimmed);
              // Translate standard format to DocsGPT internal events
              const translated = translateV1ChunkToInternalEvents(parsed);
              for (const evt of translated) {
                onEvent(
                  new MessageEvent('message', {
                    data: JSON.stringify(evt),
                  }),
                );
              }
            } catch {
              // Skip unparseable chunks
            }
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('V1 chat completion stream failed:', error);
        reject(error);
      });
  });
}

/**
 * Translate a single v1 streaming chunk to internal DocsGPT event(s).
 *
 * Standard format: {"choices": [{"delta": {"content": "chunk"}, ...}]}
 * Extension format: {"docsgpt": {"type": "source", ...}}
 */
function translateV1ChunkToInternalEvents(
  chunk: any,
): { type: string; [key: string]: any }[] {
  const events: { type: string; [key: string]: any }[] = [];

  // DocsGPT extension chunks
  if (chunk.docsgpt) {
    const ext = chunk.docsgpt;
    if (ext.type === 'source') {
      events.push({ type: 'source', source: ext.sources });
    } else if (ext.type === 'tool_call') {
      events.push({ type: 'tool_call', data: ext.data });
    } else if (ext.type === 'tool_calls_pending') {
      events.push({
        type: 'tool_calls_pending',
        data: { pending_tool_calls: ext.pending_tool_calls },
      });
    } else if (ext.type === 'id') {
      events.push({ type: 'id', id: ext.conversation_id });
    }
    return events;
  }

  // Error chunks
  if (chunk.error) {
    events.push({ type: 'error', error: chunk.error.message || 'Error' });
    return events;
  }

  // Standard choices chunks
  const choice = chunk.choices?.[0];
  if (!choice) return events;

  const delta = choice.delta || {};
  const finishReason = choice.finish_reason;

  if (delta.content) {
    events.push({ type: 'answer', answer: delta.content });
  }

  if (delta.reasoning_content) {
    events.push({ type: 'thought', thought: delta.reasoning_content });
  }

  if (delta.tool_calls) {
    for (const tc of delta.tool_calls) {
      let parsedArgs: Record<string, any> = {};
      if (tc.function?.arguments) {
        try {
          parsedArgs = JSON.parse(tc.function.arguments);
        } catch {
          // Arguments may arrive as fragments during streaming;
          // keep the raw string so downstream can accumulate it.
          parsedArgs = { _raw: tc.function.arguments };
        }
      }
      events.push({
        type: 'tool_call',
        data: {
          call_id: tc.id,
          action_name: tc.function?.name || '',
          tool_name: tc.function?.name || '',
          arguments: parsedArgs,
          status: 'requires_client_execution',
        },
      });
    }
  }

  if (finishReason === 'stop') {
    events.push({ type: 'end' });
  } else if (finishReason === 'tool_calls') {
    events.push({
      type: 'tool_calls_pending',
      data: { pending_tool_calls: [] },
    });
  }

  return events;
}

export function handleSendFeedback(
  prompt: string,
  response: string,
  feedback: FEEDBACK,
  conversation_id: string,
  prompt_index: number,
  token: string | null,
) {
  return conversationService
    .feedback(
      {
        question: prompt,
        answer: response,
        feedback: feedback,
        conversation_id: conversation_id,
        question_index: prompt_index,
      },
      token,
    )
    .then((response) => {
      if (response.ok) {
        return Promise.resolve();
      } else {
        return Promise.reject();
      }
    });
}

export function handleFetchSharedAnswerStreaming(
  question: string,
  signal: AbortSignal,
  apiKey: string,
  history: Array<any> = [],
  attachments: string[] = [],
  onEvent: (event: MessageEvent) => void,
): Promise<Answer> {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });

  return new Promise<Answer>((resolve, reject) => {
    const payload = {
      question: question,
      history: JSON.stringify(history),
      api_key: apiKey,
      save_conversation: false,
      visibility: 'hidden',
      attachments: attachments.length > 0 ? attachments : undefined,
    };
    conversationService
      .answerStream(payload, null, signal)
      .then((response) => {
        if (!response.body) throw Error('No response body');

        const reader = response.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let counterrr = 0;
        const processStream = ({
          done,
          value,
        }: ReadableStreamReadResult<Uint8Array>) => {
          if (done) {
            console.log(counterrr);
            return;
          }

          counterrr += 1;

          const chunk = decoder.decode(value);

          const lines = chunk.split('\n');

          for (let line of lines) {
            if (line.trim() == '') {
              continue;
            }
            if (line.startsWith('data:')) {
              line = line.substring(5);
            }

            const messageEvent: MessageEvent = new MessageEvent('message', {
              data: line,
            });

            onEvent(messageEvent); // handle each message
          }

          reader.read().then(processStream).catch(reject);
        };

        reader.read().then(processStream).catch(reject);
      })
      .catch((error) => {
        console.error('Connection failed:', error);
        reject(error);
      });
  });
}

export function handleFetchSharedAnswer(
  question: string,
  signal: AbortSignal,
  apiKey: string,
  attachments?: string[],
): Promise<
  | {
      result: any;
      answer: any;
      sources: any;
      query: string;
    }
  | {
      result: any;
      answer: any;
      sources: any;
      query: string;
      title: any;
    }
> {
  const payload = {
    question: question,
    api_key: apiKey,
    visibility: 'hidden',
    attachments:
      attachments && attachments.length > 0 ? attachments : undefined,
  };

  return conversationService
    .answer(payload, null, signal)
    .then((response) => {
      if (response.ok) {
        return response.json();
      } else {
        return Promise.reject(new Error(response.statusText));
      }
    })
    .then((data) => {
      const result = data.answer;
      return {
        answer: result,
        query: question,
        result,
        sources: data.sources,
        toolCalls: data.tool_calls,
      };
    });
}
