import { baseURL } from '../api/client';
import conversationService from '../api/services/conversationService';
import { Doc } from '../models/misc';
import { Answer, FEEDBACK, RetrievalPayload } from './conversationModels';
import { ToolCallsType } from './types';

/**
 * Mirrors the backend's ``_SEQUENCE_NO_RE`` (application/api/answer/
 * routes/messages.py) — only non-negative decimal integers are valid
 * cursors. Rejects empty strings (Number("") === 0), hex literals,
 * exponential notation, and anything else that ``Number(...)`` would
 * happily coerce.
 */
const _SEQUENCE_NO_RE = /^\d+$/;

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
  try {
    const text = await response.text();
    if (text) {
      try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object') {
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
  dispatch(JSON.stringify({ type: 'error', error: message }));
  return true;
}

async function _drainSseBody(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  onData: (data: string) => void,
  onId: (id: number) => void,
  shouldStop?: () => boolean,
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

export function handleFetchAnswer(
  question: string,
  signal: AbortSignal,
  token: string | null,
  selectedDocs: Doc[],
  conversationId: string | null,
  promptId: string | null,
  chunks: string,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  idempotencyKey?: string,
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
    chunks: chunks,
    isNoneDoc: selectedDocs.length === 0,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      // Handle multiple documents
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      // Handle single document (backward compatibility)
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }
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
  chunks: string,
  onEvent: (event: MessageEvent) => void,
  indx?: number,
  agentId?: string,
  attachments?: string[],
  save_conversation = true,
  modelId?: string,
  idempotencyKey?: string,
): Promise<Answer> {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversationId,
    prompt_id: promptId,
    chunks: chunks,
    isNoneDoc: selectedDocs.length === 0,
    index: indx,
    agent_id: agentId,
    save_conversation: save_conversation,
  };

  if (modelId) {
    payload.model_id = modelId;
  }

  // Add attachments to payload if they exist
  if (attachments && attachments.length > 0) {
    payload.attachments = attachments;
  }

  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      // Handle multiple documents
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      // Handle single document (backward compatibility)
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }

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
          endReceived = true;
        }
      }
    } catch {
      // Not JSON — pass through anyway; the caller handles raw lines.
    }
    onEvent(new MessageEvent('message', { data }));
  };

  const runInitialPost = async (): Promise<void> => {
    const response = await conversationService.answerStream(
      payload,
      token,
      signal,
      headers,
    );
    // Pre-stream HTTP failures with non-SSE bodies (e.g. ``check_usage``
    // returning a JSON 429) drain as zero events and would otherwise
    // be masked by the generic "Connection lost" synthetic. Convert
    // them into a typed ``error`` frame so the real message surfaces.
    if (await _handlePreStreamHttpError(response, dispatch)) return;
    if (!response.body) throw new Error('No response body');
    await _drainSseBody(response.body, signal, dispatch, (id) => {
      lastEventId = id;
    });
  };

  // Reconnect's stop predicate: as soon as ``dispatch`` flips
  // ``endReceived`` (typed ``end`` or ``error`` event seen — both
  // are terminal per the backend's contract). Without this the
  // live-tail endpoint would emit keepalives indefinitely and the
  // await would never return.
  const reconnectShouldStop = () => endReceived;

  const runReconnect = async (): Promise<void> => {
    if (!messageId) {
      throw new Error('reconnect: no message_id captured');
    }
    const url = new URL(`${baseURL}/api/messages/${messageId}/events`);
    if (lastEventId !== null) {
      url.searchParams.set('last_event_id', String(lastEventId));
    }
    const reconnectHeaders: Record<string, string> = {
      Accept: 'text/event-stream',
    };
    if (token) reconnectHeaders.Authorization = `Bearer ${token}`;
    // NB: there is no slice consumer for a synthetic ``reconnecting``
    // event yet — surface only the underlying network reality. The
    // user-visible ``Reconnecting…`` affordance is a Phase 2 follow-up
    // that needs ``conversationSlice`` to gain a status case.
    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: reconnectHeaders,
      signal,
      cache: 'no-store',
    });
    if (!response.ok || !response.body) {
      throw new Error(
        `reconnect: HTTP ${response.status} ${response.statusText}`,
      );
    }
    await _drainSseBody(
      response.body,
      signal,
      dispatch,
      (id) => {
        lastEventId = id;
      },
      reconnectShouldStop,
    );
  };

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
        // event. Anything else (network drop, gunicorn worker recycle,
        // load-balancer timeout) is a "premature close" — try one
        // reconnect via the GET /api/messages/<id>/events endpoint.
        if (!endReceived && !signal.aborted && messageId) {
          try {
            await runReconnect();
          } catch (reconnectErr) {
            console.warn('Stream reconnect failed:', reconnectErr);
          }
        }
        // If we never observed a terminal frame (reconnect 4xx/5xx,
        // network drop during reconnect, or live tail still silent),
        // synthesize one through the same ``dispatch`` path the wire
        // events use. Without this the caller's slice never transitions
        // out of ``streaming`` and the UI stays in a loading spinner
        // forever — the conversationSlice handles ``data.type === 'error'``
        // by setting status=failed.
        if (!endReceived && !signal.aborted) {
          dispatch(
            JSON.stringify({
              type: 'error',
              error:
                'Connection lost. The response could not be resumed; please try again.',
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

export function handleSubmitToolActions(
  conversationId: string,
  toolActions: {
    call_id: string;
    decision?: 'approved' | 'denied';
    comment?: string;
    result?: Record<string, any>;
  }[],
  token: string | null,
  signal: AbortSignal,
  onEvent: (event: MessageEvent) => void,
  idempotencyKey?: string,
): Promise<Answer> {
  const payload = {
    conversation_id: conversationId,
    tool_actions: toolActions,
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
          endReceived = true;
        }
      }
    } catch {
      // Not JSON — pass through anyway; the caller handles raw lines.
    }
    onEvent(new MessageEvent('message', { data }));
  };

  const runInitial = async (): Promise<void> => {
    const response = await conversationService.answerStream(
      payload,
      token,
      signal,
      headers,
    );
    // See ``handleFetchAnswerSteaming`` for the rationale: non-SSE
    // HTTP failures (e.g. ``check_usage`` 429 JSON) need to be lifted
    // into a typed ``error`` frame before they reach the drainer.
    if (await _handlePreStreamHttpError(response, dispatch)) return;
    if (!response.body) throw new Error('No response body');
    await _drainSseBody(response.body, signal, dispatch, (id) => {
      lastEventId = id;
    });
  };

  // Reconnect's stop predicate: as soon as ``dispatch`` flips
  // ``endReceived`` (typed ``end`` or ``error`` event seen — both
  // are terminal per the backend's contract). Without this the
  // live-tail endpoint would emit keepalives indefinitely and the
  // await would never return.
  const reconnectShouldStop = () => endReceived;

  const runReconnect = async (): Promise<void> => {
    if (!messageId) {
      throw new Error('reconnect: no message_id captured');
    }
    const url = new URL(`${baseURL}/api/messages/${messageId}/events`);
    if (lastEventId !== null) {
      url.searchParams.set('last_event_id', String(lastEventId));
    }
    const reconnectHeaders: Record<string, string> = {
      Accept: 'text/event-stream',
    };
    if (token) reconnectHeaders.Authorization = `Bearer ${token}`;
    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: reconnectHeaders,
      signal,
      cache: 'no-store',
    });
    if (!response.ok || !response.body) {
      throw new Error(
        `reconnect: HTTP ${response.status} ${response.statusText}`,
      );
    }
    await _drainSseBody(
      response.body,
      signal,
      dispatch,
      (id) => {
        lastEventId = id;
      },
      reconnectShouldStop,
    );
  };

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
          try {
            await runReconnect();
          } catch (reconnectErr) {
            console.warn('Tool-actions reconnect failed:', reconnectErr);
          }
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

export function handleSearch(
  question: string,
  token: string | null,
  selectedDocs: Doc[],
  conversation_id: string | null,
  chunks: string,
) {
  const payload: RetrievalPayload = {
    question: question,
    conversation_id: conversation_id,
    chunks: chunks,
    isNoneDoc: selectedDocs.length === 0,
  };
  if (selectedDocs.length > 0) {
    if (selectedDocs.length > 1) {
      // Handle multiple documents
      payload.active_docs = selectedDocs.map((doc) => doc.id!);
      payload.retriever = selectedDocs[0]?.retriever as string;
    } else if (selectedDocs.length === 1 && 'id' in selectedDocs[0]) {
      // Handle single document (backward compatibility)
      payload.active_docs = selectedDocs[0].id as string;
      payload.retriever = selectedDocs[0].retriever as string;
    }
  }
  return conversationService
    .search(payload, token)
    .then((response) => response.json())
    .then((data) => {
      return data;
    })
    .catch((err) => console.log(err));
}

export function handleSearchViaApiKey(
  question: string,
  api_key: string,
  history: Array<any> = [],
) {
  history = history.map((item) => {
    return {
      prompt: item.prompt,
      response: item.response,
      tool_calls: item.tool_calls,
    };
  });
  return conversationService
    .search(
      {
        question: question,
        history: JSON.stringify(history),
        api_key: api_key,
      },
      null,
    )
    .then((response) => response.json())
    .then((data) => {
      return data;
    })
    .catch((err) => console.log(err));
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
