import { envVar } from '@/env';
import {
  AsyncThunkPayloadCreator,
  createAsyncThunk,
  createListenerMiddleware,
  createSlice,
  PayloadAction,
} from '@reduxjs/toolkit';

import type { Agent } from '../agents/types';
import activityService from '../api/services/activityService';
import conversationService from '../api/services/conversationService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import { isPageAttended } from '../backgroundJobs/usePageVisible';
import { shownConversationId } from '../backgroundJobs/usePresence';
import { getConversations } from '../preferences/preferenceApi';
import {
  receiveConversations,
  renameConversation,
  setSelectedAgent,
} from '../preferences/preferenceSlice';
import type { RootState } from '../store';
import {
  clearAttachments,
  selectSendableAttachmentIds,
} from '../upload/uploadSlice';
import { wakeFromMetadata } from '../backgroundJobs/kinds';
import { newIdempotencyKey } from '../utils/idempotency';
import {
  appendAnswerText,
  appendThoughtText,
  hydrateSegments,
  recordToolCall,
} from './answerSegments';
import {
  type ErrorParams,
  readStreamError,
  setErrorDetail,
} from './curatedError';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
  handleV1ChatCompletionStreaming,
} from './conversationHandlers';
import {
  Answer,
  ConversationState,
  FEEDBACK,
  MessageStatus,
  Query,
  ResearchStep,
  Status,
} from './conversationModels';
import { ToolCallsType } from './types';

// Maps a server message dict into the client ``Query`` shape. Only
// terminal ``complete`` rows expose ``response``; non-terminal rows
// would carry the WAL placeholder text, which must never render.
// ``failed`` rows surface as ``error`` so they pick up Retry.
// The API stores feedback lowercase ('like' / 'dislike') so analytics can
// count it; the thumbs compare against the uppercase FEEDBACK union.
function toClientFeedback(value: unknown): FEEDBACK | undefined {
  if (typeof value !== 'string') return undefined;
  const upper = value.toUpperCase();
  return upper === 'LIKE' || upper === 'DISLIKE' ? upper : undefined;
}

const FAILED_FALLBACK = 'Generation failed before completing.';

/**
 * A failed turn's stored error as ``{message, code, params}``. The backend
 * stores curated text in ``error``, its reason in ``error_code``
 * (``context_length_exceeded``) and the values it was worded from in
 * ``error_params``; an ``error`` object with ``message``, ``code`` and
 * ``params`` is read too. Older rows carry only the text.
 */
export function readStoredError(
  error: unknown,
  code: unknown,
  params?: unknown,
): { message: string; code?: string; params?: ErrorParams } {
  if (error && typeof error === 'object') {
    const obj = error as {
      message?: unknown;
      code?: unknown;
      params?: unknown;
    };
    return readStoredError(obj.message, obj.code ?? code, obj.params ?? params);
  }
  const stored = readStreamError({ error, code, params });
  return { ...stored, message: stored.message || FAILED_FALLBACK };
}

export function mapServerQueryToClient(raw: any): Query {
  const status = raw?.status as MessageStatus | undefined;
  const isTerminalComplete = status === 'complete';
  const isFailed = status === 'failed';
  const metadata = raw?.metadata || {};

  // Empty arrays are JS-truthy; coercing to undefined keeps the
  // renderer from rendering a blank bubble for in-flight rows and
  // matches the shape live-stream queries start with.
  const toolCalls = Array.isArray(raw?.tool_calls) ? raw.tool_calls : undefined;
  const sources = Array.isArray(raw?.sources) ? raw.sources : undefined;
  const query: Query = {
    prompt: raw?.prompt ?? '',
    feedback: toClientFeedback(raw?.feedback),
    thought: raw?.thought ?? undefined,
    sources: sources && sources.length > 0 ? sources : undefined,
    tool_calls: toolCalls && toolCalls.length > 0 ? toolCalls : undefined,
    workflow_run_id: raw?.workflow_run_id ?? undefined,
    attachments: raw?.attachments ?? undefined,
    messageId: raw?.message_id ?? undefined,
    messageStatus: status,
    requestId: raw?.request_id ?? undefined,
    lastHeartbeatAt: raw?.last_heartbeat_at ?? undefined,
  };

  const wake = wakeFromMetadata(metadata);
  if (wake) query.wake = wake;

  if (
    isTerminalComplete ||
    (isFailed && metadata.error_code === 'time_limit')
  ) {
    query.response = raw?.response ?? '';
    // The order the parts streamed in, saved with the message.
    query.segments = hydrateSegments(
      raw?.segments ?? metadata.segments,
      query.response,
      query.thought,
    );
  }
  if (isFailed) {
    const stored = readStoredError(
      metadata.error,
      metadata.error_code,
      metadata.error_params,
    );
    query.error = stored.message;
    setErrorDetail(query, stored.code, stored.params);
  }
  return query;
}

// Placeholder still being produced server-side; client should tail
// rather than treat as idle.
export function isInFlightMessage(query: Query | undefined): boolean {
  if (!query) return false;
  return (
    query.messageStatus === 'pending' || query.messageStatus === 'streaming'
  );
}

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
};

const API_STREAMING = envVar('VITE_API_STREAMING') === 'true';
const USE_V1_API = envVar('VITE_USE_V1_API') === 'true';

let abortController: AbortController | null = null;
export function handleAbort() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

/**
 * A thunk that streams into the chat. It gets the stream's signal; once it
 * settles there is no stream left for Stop to close.
 */
function streamed<Arg, Result, Api>(
  body: (arg: Arg, api: Api, signal: AbortSignal) => Promise<Result>,
): (arg: Arg, api: Api) => Promise<Result> {
  return async (arg, api) => {
    if (abortController) abortController.abort();
    const controller = new AbortController();
    abortController = controller;
    try {
      return await body(arg, api, controller.signal);
    } finally {
      if (abortController === controller) abortController = null;
    }
  };
}

/** How long the chat's Stop waits for the server to take it before closing. */
export const STOP_REQUEST_TIMEOUT_MS = 1000;

/** Whether a Stop is out: another press while it is would send it again. */
let stopping = false;

/**
 * The chat's Stop. Tells the server first, so the answer is saved as stopped
 * rather than as a dropped connection, then closes the stream. An answer
 * stopped before it wrote anything says so at once, as it will after a
 * reload.
 */
export const stopAnswer = createAsyncThunk<void, void>(
  'conversation/stopAnswer',
  async (_arg, { dispatch, getState }) => {
    stopping = true;
    try {
      await stop(dispatch, getState);
    } finally {
      stopping = false;
    }
  },
  { condition: () => !stopping },
);

async function stop(
  dispatch: (action: unknown) => unknown,
  getState: () => unknown,
): Promise<void> {
  const controller = abortController;
  const { conversation, preference } = getState() as RootState;
  const conversationId = conversation.conversationId;
  const index = conversation.queries.length - 1;
  const messageId = conversation.queries[index]?.messageId;
  let taken = false;
  // Not only a stream of this tab's: an answer picked back up after a
  // reload is followed by polling, and only the server can stop it.
  if (messageId && conversation.status === 'loading') {
    taken = await Promise.race([
      activityService.stopMessage(messageId, preference.token).then(
        () => true,
        () => false,
      ),
      new Promise<boolean>((resolve) =>
        setTimeout(() => resolve(false), STOP_REQUEST_TIMEOUT_MS),
      ),
    ]);
  }
  if (abortController === controller) {
    handleAbort();
    // A closed stream never gets its terminal event, which is what ends
    // loading. An answer picked back up is left to its tail, which ends it
    // once the server has saved the stop.
    if (
      controller &&
      (getState() as RootState).conversation.conversationId === conversationId
    )
      dispatch(conversationSlice.actions.setStatus('idle'));
  }
  // The user may have opened another chat while the request was out: mark
  // only the answer that was stopped, in the chat it belongs to.
  const after = (getState() as RootState).conversation;
  if (!taken || after.conversationId !== conversationId) return;
  const at = after.queries.findIndex((query) => query.messageId === messageId);
  const query = after.queries[at];
  if (query && !query.response && !query.error) {
    dispatch(
      conversationSlice.actions.raiseError({
        conversationId,
        index: at,
        message: 'Stopped before any response was produced.',
        code: 'stopped',
      }),
    );
  }
}

// Loads a conversation and applies it to the slice. Returns
// ``{data, stale}``: ``stale`` true means a newer load has superseded
// this one (or Redux already matches), so callers should not react to
// the returned data; ``data`` null with ``stale`` false means 404.
export type LoadConversationResult = {
  data: any | null;
  stale: boolean;
};

// The fields of a loaded chat that say which agent it belongs to.
export type ConversationAgentFields = {
  agent_id?: string | null;
  is_shared_usage?: boolean;
  shared_token?: string | null;
};

export type LoadConversationArgs = {
  id: string;
  force?: boolean;
  // The chat's agent (null for none), awaited before anything is applied
  // so its messages and agent card change in one render. Without it the
  // selected agent is left alone.
  resolveAgent?: (data: ConversationAgentFields) => Promise<Agent | null>;
  // A refresh nobody asked for (an event): dropped when this tab starts
  // streaming an answer before it lands, which it would otherwise overwrite.
  unlessStreaming?: boolean;
};

let loadSeq = 0;

export const loadConversation = createAsyncThunk<
  LoadConversationResult,
  LoadConversationArgs
>('loadConversation', async (args, { dispatch, getState }) => {
  const { id, force, resolveAgent, unlessStreaming } = args;
  const seq = ++loadSeq;
  const state = getState() as RootState;
  const token = state.preference.token;
  if (!force && state.conversation.conversationId === id) {
    return { data: null, stale: true };
  }
  const response = await conversationService.getConversation(id, token);
  if (!response.ok) {
    return { data: null, stale: false };
  }
  const data = await response.json();
  if (!data) return { data: null, stale: false };
  let agent: Agent | null | undefined;
  try {
    agent = resolveAgent ? await resolveAgent(data) : undefined;
  } catch (error) {
    // A superseded load must not reject: its caller would navigate away
    // from the newer chat.
    if (seq !== loadSeq) return { data: null, stale: true };
    throw error;
  }

  // A later loadConversation has been issued; drop our writes so its
  // result wins, and tell the caller not to navigate off our return.
  if (seq !== loadSeq) {
    return { data: null, stale: true };
  }
  if (
    unlessStreaming &&
    (getState() as RootState).conversation.status === 'loading'
  ) {
    return { data: null, stale: true };
  }

  const mappedQueries = (data.queries || []).map(mapServerQueryToClient);
  if (agent !== undefined) dispatch(setSelectedAgent(agent));
  dispatch(conversationSlice.actions.setConversation(mappedQueries));
  dispatch(
    conversationSlice.actions.updateConversationId({
      query: { conversationId: id },
    }),
  );

  // Only tail the trailing message; earlier in-flight rows are rare.
  const lastIdx = mappedQueries.length - 1;
  const lastQuery = mappedQueries[lastIdx];
  if (lastQuery && lastQuery.messageId && isInFlightMessage(lastQuery)) {
    dispatch(
      tailInFlightMessage({
        messageId: lastQuery.messageId,
        index: lastIdx,
        conversationId: id,
      }),
    );
  }
  return { data, stale: false };
});

type FetchAnswerArgs = {
  question: string;
  indx?: number;
  attachmentIds?: string[];
};

export const fetchAnswer = createAsyncThunk<Answer, FetchAnswerArgs>(
  'fetchAnswer',
  streamed(answerQuestion),
);

async function answerQuestion(
  arg: FetchAnswerArgs,
  {
    dispatch,
    getState,
  }: Parameters<AsyncThunkPayloadCreator<Answer, FetchAnswerArgs>>[1],
  signal: AbortSignal,
): Promise<Answer> {
  const { question, indx } = arg;

  let isSourceUpdated = false;
  const state = getState() as RootState;
  // Explicit ids (new sends and retries pass the ids bound to the turn)
  // keep the wire payload in sync with what the query row displays.
  // The fallback reads the composer state for callers that predate the
  // argument and consumes it, which loses the ids on a later retry.
  let attachmentIds: string[];
  if (arg.attachmentIds !== undefined) {
    attachmentIds = arg.attachmentIds;
  } else {
    attachmentIds = selectSendableAttachmentIds(state);
    if (attachmentIds.length > 0) {
      dispatch(clearAttachments());
    }
  }

  // Mutable so the SSE handler can adopt a server-assigned id and
  // keep passing it to reducer guards once the early ``message_id``
  // event lands.
  let currentConversationId = state.conversation.conversationId;
  const modelId =
    state.preference.selectedAgent?.default_model_id ||
    state.preference.selectedModel?.id;

  // Reuse the key on the target Query when present (retry path),
  // else mint and persist so a later retry can re-send it.
  const targetIndexForKey =
    indx ?? Math.max(state.conversation.queries.length - 1, 0);
  let idempotencyKey =
    state.conversation.queries[targetIndexForKey]?.idempotencyKey;
  if (!idempotencyKey) {
    idempotencyKey = newIdempotencyKey();
    dispatch(
      conversationSlice.actions.updateQuery({
        index: targetIndexForKey,
        query: { idempotencyKey },
      }),
    );
  }

  if (state.preference) {
    const agentKey = state.preference.selectedAgent?.key;
    if (USE_V1_API && agentKey) {
      // Build history from prior queries for v1 format
      const v1History = state.conversation.queries
        .filter((q) => q.response)
        .map((q) => ({ prompt: q.prompt, response: q.response || '' }));

      await handleV1ChatCompletionStreaming(
        question,
        signal,
        agentKey,
        v1History,
        (event) => {
          const data = JSON.parse(event.data);
          const targetIndex = indx ?? state.conversation.queries.length - 1;

          // Live Redux check; the closure ``state`` is a stale snapshot.
          if (
            currentConversationId ===
            (getState() as RootState).conversation.conversationId
          ) {
            if (data.type === 'end') {
              dispatch(conversationSlice.actions.setStatus('idle'));
              // Through the shared refresh, so a generated title announced while
              // it runs gets a list read after it (see refreshConversationList).
              void refreshConversationList(getState, dispatch);
              if (!isSourceUpdated) {
                dispatch(
                  updateStreamingSource({
                    conversationId: currentConversationId,
                    index: targetIndex,
                    query: { sources: [] },
                  }),
                );
              }
            } else if (data.type === 'id') {
              const currentState = getState() as RootState;
              if (currentState.conversation.conversationId === null) {
                dispatch(
                  updateConversationId({
                    query: { conversationId: data.id },
                  }),
                );
              }
            } else if (data.type === 'message_id') {
              if (data.conversation_id) {
                const currentState = getState() as RootState;
                if (currentState.conversation.conversationId === null) {
                  // setConversationId leaves status='loading'; the
                  // status-touching updateConversationId would flip it
                  // to 'idle' and drop subsequent chunks.
                  dispatch(
                    conversationSlice.actions.setConversationId(
                      data.conversation_id,
                    ),
                  );
                  currentConversationId = data.conversation_id;
                }
              }
              dispatch(
                conversationSlice.actions.updateMessageMeta({
                  index: targetIndex,
                  messageId: data.message_id,
                  requestId: data.request_id,
                }),
              );
            } else if (data.type === 'thought') {
              dispatch(
                updateThought({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { thought: data.thought },
                }),
              );
            } else if (data.type === 'source') {
              isSourceUpdated = true;
              dispatch(
                updateStreamingSource({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { sources: data.source ?? [] },
                }),
              );
            } else if (data.type === 'tool_call') {
              dispatch(
                updateToolCall({
                  index: targetIndex,
                  tool_call: data.data as ToolCallsType,
                }),
              );
            } else if (data.type === 'tool_calls_pending') {
              dispatch(
                conversationSlice.actions.setStatus('awaiting_tool_actions'),
              );
            } else if (data.type === 'notice') {
              dispatch(
                conversationSlice.actions.raiseNotice({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  message: data.notice ?? '',
                }),
              );
            } else if (data.type === 'guardrail') {
              if (data.retract) {
                dispatch(
                  conversationSlice.actions.retractResponse({
                    conversationId: currentConversationId,
                    index: targetIndex,
                  }),
                );
              }
            } else if (data.type === 'error') {
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  ...readStreamError(data),
                }),
              );
            } else {
              dispatch(
                updateStreamingQuery({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { response: data.answer },
                }),
              );
            }
          }
        },
        undefined,
        attachmentIds.length > 0 ? attachmentIds : undefined,
      );
    } else if (API_STREAMING) {
      await handleFetchAnswerSteaming(
        question,
        signal,
        state.preference.token,
        state.preference.selectedDocs || [],
        currentConversationId,
        state.preference.prompt.id,
        state.preference.chunks,
        (event) => {
          const data = JSON.parse(event.data);
          const targetIndex = indx ?? state.conversation.queries.length - 1;

          // Live Redux check; the closure ``state`` is a stale snapshot.
          if (
            currentConversationId ===
            (getState() as RootState).conversation.conversationId
          ) {
            if (data.type === 'end') {
              dispatch(conversationSlice.actions.setStatus('idle'));
              // Only update research status if this query has research data
              const currentState = getState() as RootState;
              if (currentState.conversation.queries[targetIndex]?.research) {
                dispatch(
                  updateResearchProgress({
                    index: targetIndex,
                    progress: { status: 'complete' },
                  }),
                );
              }
              // Through the shared refresh, so a generated title announced while
              // it runs gets a list read after it (see refreshConversationList).
              void refreshConversationList(getState, dispatch);
              if (!isSourceUpdated) {
                dispatch(
                  updateStreamingSource({
                    conversationId: currentConversationId,
                    index: targetIndex,
                    query: { sources: [] },
                  }),
                );
              }
            } else if (data.type === 'id') {
              // Only update the conversationId if it's currently null
              const currentState = getState() as RootState;
              if (currentState.conversation.conversationId === null) {
                dispatch(
                  updateConversationId({
                    query: { conversationId: data.id },
                  }),
                );
              }
            } else if (data.type === 'message_id') {
              if (data.conversation_id) {
                const currentState = getState() as RootState;
                if (currentState.conversation.conversationId === null) {
                  // setConversationId leaves status='loading'; the
                  // status-touching updateConversationId would flip it
                  // to 'idle' and drop subsequent chunks.
                  dispatch(
                    conversationSlice.actions.setConversationId(
                      data.conversation_id,
                    ),
                  );
                  currentConversationId = data.conversation_id;
                }
              }
              dispatch(
                conversationSlice.actions.updateMessageMeta({
                  index: targetIndex,
                  messageId: data.message_id,
                  requestId: data.request_id,
                }),
              );
            } else if (data.type === 'thought') {
              const result = data.thought;
              dispatch(
                updateThought({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { thought: result },
                }),
              );
            } else if (data.type === 'source') {
              isSourceUpdated = true;
              dispatch(
                updateStreamingSource({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { sources: data.source ?? [] },
                }),
              );
            } else if (data.type === 'tool_call') {
              dispatch(
                updateToolCall({
                  index: targetIndex,
                  tool_call: data.data as ToolCallsType,
                }),
              );
            } else if (data.type === 'tool_calls_pending') {
              dispatch(
                conversationSlice.actions.setStatus('awaiting_tool_actions'),
              );
            } else if (data.type === 'workflow_run') {
              dispatch(
                conversationSlice.actions.setWorkflowRunId({
                  index: targetIndex,
                  workflowRunId: data.workflow_run_id,
                }),
              );
            } else if (data.type === 'research_plan') {
              dispatch(
                updateResearchPlan({
                  index: targetIndex,
                  plan: data.data.steps,
                  complexity: data.data.complexity,
                }),
              );
            } else if (data.type === 'research_progress') {
              dispatch(
                updateResearchProgress({
                  index: targetIndex,
                  progress: data.data,
                }),
              );
            } else if (data.type === 'notice') {
              dispatch(
                conversationSlice.actions.raiseNotice({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  message: data.notice ?? '',
                }),
              );
            } else if (data.type === 'guardrail') {
              if (data.retract) {
                dispatch(
                  conversationSlice.actions.retractResponse({
                    conversationId: currentConversationId,
                    index: targetIndex,
                  }),
                );
              }
            } else if (data.type === 'error') {
              // set status to 'failed'
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  ...readStreamError(data),
                }),
              );
            } else if (data.type === 'structured_answer') {
              dispatch(
                updateStreamingQuery({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: {
                    response: data.answer,
                    structured: data.structured,
                    schema: data.schema,
                  },
                }),
              );
            } else {
              dispatch(
                updateStreamingQuery({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  query: { response: data.answer },
                }),
              );
            }
          }
        },
        indx,
        state.preference.selectedAgent?.id,
        attachmentIds,
        true,
        modelId,
        idempotencyKey,
      );
    } else {
      const answer = await handleFetchAnswer(
        question,
        signal,
        state.preference.token,
        state.preference.selectedDocs || [],
        state.conversation.conversationId,
        state.preference.prompt.id,
        state.preference.chunks,
        state.preference.selectedAgent?.id,
        attachmentIds,
        true,
        modelId,
        idempotencyKey,
      );
      if (answer) {
        let sourcesPrepped = [];
        sourcesPrepped = answer.sources.map((source: { title: string }) => {
          if (source && source.title) {
            const titleParts = source.title.split('/');
            return {
              ...source,
              title: titleParts[titleParts.length - 1],
            };
          }
          return source;
        });

        const targetIndex = indx ?? state.conversation.queries.length - 1;

        dispatch(
          updateQuery({
            index: targetIndex,
            query: {
              response: answer.answer,
              thought: answer.thought,
              sources: sourcesPrepped,
              tool_calls: answer.toolCalls,
            },
          }),
        );
        dispatch(
          updateConversationId({
            query: { conversationId: answer.conversationId },
          }),
        );
        // Through the shared refresh, so a generated title announced while
        // it runs gets a list read after it (see refreshConversationList).
        void refreshConversationList(getState, dispatch);
        dispatch(conversationSlice.actions.setStatus('idle'));
      }
    }
  }
  return {
    conversationId: null,
    title: null,
    answer: '',
    query: question,
    result: '',
    thought: '',
    sources: [],
    tool_calls: [],
  };
}

// Tail-polls the placeholder until terminal status, navigation away,
// or hard timeout. First poll fires immediately so rows that are
// already terminal resolve without delay.
const TAIL_POLL_INTERVAL_MS = 2000;
const TAIL_MAX_POLL_DURATION_MS = 10 * 60 * 1000;

/** The error code of a decision for an approval that is no longer waiting. */
export const NOT_PENDING_CODE = 'tool_call_not_pending';

/** Why a ``tool.approval.cleared`` means the open chat shows a stale approval. */
const APPROVAL_RETIRED_REASONS = new Set(['moved_on', 'expired']);

/** Whether a turn's calls include one paused for the user to decide or run. */
export function isWaitingOnUser(toolCalls: unknown): boolean {
  return (
    Array.isArray(toolCalls) &&
    toolCalls.some(
      (call) =>
        call?.status === 'awaiting_approval' ||
        call?.status === 'requires_client_execution',
    )
  );
}

/** Messages whose tail found them deleted and reloaded their chat for it. */
const reloadedForGoneMessage = new Set<string>();

export const tailInFlightMessage = createAsyncThunk<
  void,
  { messageId: string; index: number; conversationId: string }
>(
  'tailInFlightMessage',
  async ({ messageId, index, conversationId }, { dispatch, getState }) => {
    const initialState = getState() as RootState;
    const token = initialState.preference.token;
    const start = Date.now();
    dispatch(conversationSlice.actions.setStatus('loading'));

    while (Date.now() - start < TAIL_MAX_POLL_DURATION_MS) {
      const cur = (getState() as RootState).conversation.conversationId;
      if (cur !== conversationId) return;

      let resp: Response;
      try {
        resp = await conversationService.tailMessage(messageId, token);
      } catch {
        await new Promise((r) => setTimeout(r, TAIL_POLL_INTERVAL_MS));
        continue;
      }

      // 404 → row deleted: the conversation was wiped, or a continuation
      // ended silent or failed and took its message back out. Reload the
      // chat if it is still open, so the message does not linger.
      if (resp.status === 404) {
        // A newer answer started in this chat meanwhile: it owns the status now.
        const now = (getState() as RootState).conversation;
        if (
          now.conversationId !== conversationId ||
          now.queries[now.queries.length - 1]?.messageId !== messageId
        )
          return;
        dispatch(conversationSlice.actions.setStatus('idle'));
        // Once per message: a reload that still lists it must not tail it again and again.
        if (
          !reloadedForGoneMessage.has(messageId) &&
          (getState() as RootState).conversation.conversationId ===
            conversationId
        ) {
          reloadedForGoneMessage.add(messageId);
          dispatch(
            loadConversation({
              id: conversationId,
              force: true,
              unlessStreaming: true,
            }),
          );
        }
        return;
      }

      if (!resp.ok) {
        await new Promise((r) => setTimeout(r, TAIL_POLL_INTERVAL_MS));
        continue;
      }

      const data = await resp.json();
      dispatch(
        conversationSlice.actions.applyMessageTail({ index, tail: data }),
      );

      const status = data?.status as MessageStatus | undefined;
      if (status === 'complete' || status === 'failed') {
        dispatch(
          conversationSlice.actions.setStatus(
            status === 'failed' ? 'failed' : 'idle',
          ),
        );
        return;
      }
      // Paused for the user (an approval, a client-side tool): nothing is
      // generating, so wait as a live pause does, not with "Generating…"
      // and Stop. The decision resumes the turn in a new stream.
      if (isWaitingOnUser(data?.tool_calls)) {
        dispatch(conversationSlice.actions.setStatus('awaiting_tool_actions'));
        return;
      }
      await new Promise((r) => setTimeout(r, TAIL_POLL_INTERVAL_MS));
    }
    // Hard timeout: drop status to idle so the user can interact again.
    dispatch(conversationSlice.actions.setStatus('idle'));
  },
);

type SubmitToolActionsArgs = {
  toolActions: {
    call_id: string;
    decision?: 'approved' | 'denied';
    comment?: string;
    result?: Record<string, any>;
  }[];
};

export const submitToolActions = createAsyncThunk<void, SubmitToolActionsArgs>(
  'submitToolActions',
  streamed(sendToolActions),
);

async function sendToolActions(
  { toolActions }: SubmitToolActionsArgs,
  {
    dispatch,
    getState,
  }: Parameters<AsyncThunkPayloadCreator<void, SubmitToolActionsArgs>>[1],
  signal: AbortSignal,
): Promise<void> {
  const state = getState() as RootState;
  const conversationId = state.conversation.conversationId;
  if (!conversationId) {
    const targetIndex = state.conversation.queries.length - 1;
    if (targetIndex >= 0) {
      dispatch(
        conversationSlice.actions.raiseError({
          conversationId: null,
          index: targetIndex,
          message:
            'Cannot submit decision — the conversation was not initialized. Please retry the question.',
        }),
      );
    }
    dispatch(conversationSlice.actions.setStatus('failed'));
    return;
  }

  dispatch(conversationSlice.actions.setStatus('loading'));

  // Fresh per submission: a tool decision is its own logical action.
  const idempotencyKey = newIdempotencyKey();
  await handleSubmitToolActions(
    conversationId,
    toolActions,
    state.preference.token,
    signal,
    (event) => {
      const data = JSON.parse(event.data);
      const targetIndex = state.conversation.queries.length - 1;

      if (data.type === 'end') {
        dispatch(conversationSlice.actions.setStatus('idle'));
        // Through the shared refresh, so a generated title announced while
        // it runs gets a list read after it (see refreshConversationList).
        void refreshConversationList(getState, dispatch);
      } else if (data.type === 'id') {
        // conversation ID already set
      } else if (data.type === 'message_id') {
        // Re-stamp; continuation reuses the original placeholder.
        dispatch(
          conversationSlice.actions.updateMessageMeta({
            index: targetIndex,
            messageId: data.message_id,
            requestId: data.request_id,
          }),
        );
      } else if (data.type === 'thought') {
        dispatch(
          updateThought({
            conversationId,
            index: targetIndex,
            query: { thought: data.thought },
          }),
        );
      } else if (data.type === 'source') {
        dispatch(
          updateStreamingSource({
            conversationId,
            index: targetIndex,
            query: { sources: data.source ?? [] },
          }),
        );
      } else if (data.type === 'tool_call') {
        dispatch(
          updateToolCall({
            index: targetIndex,
            tool_call: data.data as ToolCallsType,
          }),
        );
      } else if (data.type === 'tool_calls_pending') {
        dispatch(conversationSlice.actions.setStatus('awaiting_tool_actions'));
      } else if (data.type === 'notice') {
        dispatch(
          conversationSlice.actions.raiseNotice({
            conversationId,
            index: targetIndex,
            message: data.notice ?? '',
          }),
        );
      } else if (data.type === 'guardrail') {
        // A resumed turn is still the same turn: the output guard runs on the
        // continuation too, so this path needs the same retraction as the
        // initial stream or the blocked text stays on screen until reload.
        if (data.retract) {
          dispatch(
            conversationSlice.actions.retractResponse({
              conversationId,
              index: targetIndex,
            }),
          );
        }
      } else if (data.type === 'error' && data.code === NOT_PENDING_CODE) {
        // The approval is over (another tab moved on, decided it, or it
        // expired); nothing ran. Show the turn as it ended, not a failure.
        dispatch(loadConversation({ id: conversationId, force: true }));
      } else if (data.type === 'error') {
        dispatch(conversationSlice.actions.setStatus('failed'));
        dispatch(
          conversationSlice.actions.raiseError({
            conversationId,
            index: targetIndex,
            ...readStreamError(data),
          }),
        );
      } else if (data.type === 'answer') {
        dispatch(
          updateStreamingQuery({
            conversationId,
            index: targetIndex,
            query: { response: data.answer },
          }),
        );
      }
    },
    idempotencyKey,
  );
}

export const conversationSlice = createSlice({
  name: 'conversation',
  initialState,
  reducers: {
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
    },
    setConversation(state, action: PayloadAction<Query[]>) {
      state.queries = action.payload;
    },
    resendQuery(
      state,
      action: PayloadAction<{
        index: number;
        prompt: string;
        keepIdempotencyKey?: boolean;
      }>,
    ) {
      const { index, prompt, keepIdempotencyKey } = action.payload;
      if (index < 0 || index >= state.queries.length) return;

      state.queries.splice(index + 1);
      state.queries[index].prompt = prompt;
      delete state.queries[index].response;
      delete state.queries[index].thought;
      delete state.queries[index].sources;
      delete state.queries[index].tool_calls;
      delete state.queries[index].segments;
      delete state.queries[index].error;
      delete state.queries[index].errorCode;
      delete state.queries[index].errorParams;
      delete state.queries[index].structured;
      delete state.queries[index].schema;
      delete state.queries[index].feedback;
      delete state.queries[index].research;
      // A new run answers it; the old run's files are not this answer's.
      delete state.queries[index].workflow_run_id;
      // Drop stale WAL refs; the next stream's message_id event repopulates.
      delete state.queries[index].messageId;
      delete state.queries[index].messageStatus;
      delete state.queries[index].requestId;
      delete state.queries[index].lastHeartbeatAt;
      // Retry keeps the key so the server can dedupe; Edit drops it.
      if (!keepIdempotencyKey) {
        delete state.queries[index].idempotencyKey;
      }
    },
    updateStreamingQuery(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { conversationId, index, query } = action.payload;
      // Only update if this update is for the current conversation
      if (state.status === 'idle' || state.conversationId !== conversationId)
        return;

      if (query.response != undefined) {
        state.queries[index].response =
          (state.queries[index].response || '') + query.response;
        if (!state.queries[index].segments) state.queries[index].segments = [];
        appendAnswerText(state.queries[index].segments, query.response);
      }

      if (query.structured !== undefined) {
        state.queries[index].structured = query.structured;
      }

      if (query.schema !== undefined) {
        state.queries[index].schema = query.schema;
      }
    },
    updateConversationId(
      state,
      action: PayloadAction<{ query: Partial<Query> }>,
    ) {
      state.conversationId = action.payload.query.conversationId ?? null;
      state.status = 'idle';
    },
    // Sets id without touching status; used mid-stream where the
    // status-flipping updateConversationId would drop later chunks.
    setConversationId(state, action: PayloadAction<string | null>) {
      state.conversationId = action.payload;
    },
    updateThought(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { conversationId, index, query } = action.payload;
      if (state.conversationId !== conversationId) return;

      if (query.thought != undefined) {
        state.queries[index].thought =
          (state.queries[index].thought || '') + query.thought;
        if (!state.queries[index].segments) state.queries[index].segments = [];
        appendThoughtText(state.queries[index].segments, query.thought);
      }
    },
    updateStreamingSource(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (query.sources !== undefined)
        state.queries[index].sources = query.sources;
    },
    updateToolCall(state, action) {
      const { index, tool_call } = action.payload;

      if (!state.queries[index].tool_calls) {
        state.queries[index].tool_calls = [];
      }

      const existingIndex = state.queries[index].tool_calls.findIndex(
        (call) => call.call_id === tool_call.call_id,
      );

      if (existingIndex !== -1) {
        const existingCall = state.queries[index].tool_calls[existingIndex];
        state.queries[index].tool_calls[existingIndex] = {
          ...existingCall,
          ...tool_call,
        };
      } else state.queries[index].tool_calls.push(tool_call);

      if (!state.queries[index].segments) state.queries[index].segments = [];
      recordToolCall(state.queries[index].segments, tool_call.call_id);
    },
    // Records the workflow run id so the answer bubble can render the run's
    // produced artifacts (useRunArtifacts lists them by this id).
    setWorkflowRunId(
      state,
      action: PayloadAction<{ index: number; workflowRunId: string }>,
    ) {
      const { index, workflowRunId } = action.payload;
      const query = state.queries[index];
      if (!query || !workflowRunId) return;
      query.workflow_run_id = workflowRunId;
    },
    updateResearchPlan(
      state,
      action: PayloadAction<{
        index: number;
        plan: ResearchStep[];
        complexity?: string;
      }>,
    ) {
      const { index, plan, complexity } = action.payload;
      if (!state.queries[index].research) {
        state.queries[index].research = {};
      }
      state.queries[index].research!.plan = plan.map((step) => ({
        ...step,
        status: 'pending',
      }));
      if (complexity) {
        state.queries[index].research!.complexity = complexity;
      }
    },
    updateResearchProgress(
      state,
      action: PayloadAction<{
        index: number;
        progress: {
          status?: string;
          step?: number;
          total?: number;
          query?: string;
          elapsed_seconds?: number;
          tokens_used?: number;
        };
      }>,
    ) {
      const { index, progress } = action.payload;
      if (!state.queries[index].research) {
        state.queries[index].research = {};
      }
      const research = state.queries[index].research!;
      if (progress.elapsed_seconds !== undefined) {
        research.elapsed_seconds = progress.elapsed_seconds;
      }
      if (progress.tokens_used !== undefined) {
        research.tokens_used = progress.tokens_used;
      }
      // Update individual step status when step number is present
      if (progress.step !== undefined) {
        if (!research.plan) {
          research.plan = [];
        }
        const stepIndex = progress.step - 1;
        // Dynamically add step if it doesn't exist yet
        while (research.plan.length <= stepIndex) {
          research.plan.push({
            query: progress.query || `Step ${research.plan.length + 1}`,
            status: 'pending',
          });
        }
        if (
          progress.status === 'researching' ||
          progress.status === 'complete'
        ) {
          research.plan[stepIndex].status = progress.status;
        }
        if (progress.query) {
          research.plan[stepIndex].query = progress.query;
        }
        // Keep top-level status as "researching" while steps are running
        research.status = 'researching';
      } else if (progress.status) {
        // Top-level status updates (planning, synthesizing)
        research.status = progress.status;
      }
    },
    updateQuery(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      state.queries[index] = {
        ...state.queries[index],
        ...query,
      };
    },
    setStatus(state, action: PayloadAction<Status>) {
      state.status = action.payload;
    },
    updateMessageMeta(
      state,
      action: PayloadAction<{
        index: number;
        messageId?: string;
        requestId?: string;
      }>,
    ) {
      const { index, messageId, requestId } = action.payload;
      const query = state.queries[index];
      if (!query) return;
      if (messageId) query.messageId = messageId;
      if (requestId) query.requestId = requestId;
      // Mirror the server-side default so a refresh sees 'pending'.
      if (!query.messageStatus) query.messageStatus = 'pending';
    },
    applyMessageTail(
      state,
      action: PayloadAction<{ index: number; tail: any }>,
    ) {
      const { index, tail } = action.payload;
      const query = state.queries[index];
      if (!query) return;
      // A tail carries the order the server rebuilt from its journal when
      // it has one; otherwise the live order is left alone: dropping it here
      // left the stream reducers rebuilding a partial one from the next
      // delta, which hid every step that came before. It is rendering that
      // decides, per answer, whether the recorded order still accounts for
      // the snapshot or synthesis has to take over.
      const status = tail?.status as MessageStatus | undefined;
      query.messageStatus = status;
      query.lastHeartbeatAt = tail?.last_heartbeat_at ?? query.lastHeartbeatAt;
      if (status === 'failed') {
        // Surface as error so the placeholder text never renders.
        const stored = readStoredError(
          tail?.error,
          tail?.error_code,
          tail?.error_params,
        );
        query.error = stored.message;
        setErrorDetail(query, stored.code, stored.params);
        if (stored.code !== 'time_limit') {
          delete query.response;
          return;
        }
        // A failed time-limit tail still carries the saved answer's details.
        // Apply them below, preserving already streamed text if it is absent.
      }
      // /tail returns reconstructed partials mid-stream so a second tab
      // can render the in-flight bubble; spinner is driven by status.
      const incomingResponse = tail?.response;
      if (typeof incomingResponse === 'string') {
        query.response = incomingResponse;
      } else if (status === 'complete') {
        query.response = '';
      }
      if (typeof tail?.thought === 'string') {
        query.thought = tail.thought;
      }
      if (Array.isArray(tail?.sources) && tail.sources.length > 0) {
        query.sources = tail.sources;
      }
      if (Array.isArray(tail?.tool_calls) && tail.tool_calls.length > 0) {
        query.tool_calls = tail.tool_calls;
      }
      // The order the turn streamed in, rebuilt by the server from its
      // journal: without it every tool card renders above the text.
      const tailSegments = hydrateSegments(
        tail?.segments,
        query.response,
        query.thought,
      );
      if (tailSegments) query.segments = tailSegments;
      if (status === 'complete') {
        delete query.error;
        delete query.errorCode;
        delete query.errorParams;
      }
    },
    raiseError(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        message: string;
        /** Why the turn failed (``context_length_exceeded``), when known. */
        code?: string;
        /** The values a curated error was worded from. */
        params?: ErrorParams;
      }>,
    ) {
      const { conversationId, index, message, code, params } = action.payload;
      if (state.conversationId !== conversationId) return;

      state.queries[index].error = message;
      setErrorDetail(state.queries[index], code, params);
    },

    // Non-fatal counterpart to ``raiseError``: records a notice on the query
    // (e.g. some workflow input documents were dropped) WITHOUT setting the
    // 'failed' status, so the turn keeps streaming and can still complete.
    raiseNotice(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        message: string;
      }>,
    ) {
      const { conversationId, index, message } = action.payload;
      if (state.conversationId !== conversationId) return;
      if (!state.queries[index]) return;

      state.queries[index].notice = message;
    },

    retractResponse(
      state,
      action: PayloadAction<{ conversationId: string | null; index: number }>,
    ) {
      // A guardrail tripped after tokens were already rendered. The backend
      // has replaced the persisted message with the block message, so drop the
      // partial answer here too — otherwise the leaked text stays on screen
      // until reload and contradicts what is in the database.
      const { conversationId, index } = action.payload;
      if (state.conversationId !== conversationId) return;
      if (!state.queries[index]) return;

      state.queries[index].response = '';
      state.queries[index].thought = '';
      // The recorded order still holds the blocked text; the backend resets it
      // too. The tool calls stay, as they do on the saved turn.
      delete state.queries[index].segments;
    },

    resetConversation: (state) => {
      state.queries = initialState.queries;
      state.status = initialState.status;
      state.conversationId = initialState.conversationId;
      handleAbort();
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchAnswer.pending, (state) => {
        state.status = 'loading';
        // Sending a new message moves past a turn still waiting on an
        // approval: the server records those calls as never run, and so does
        // this view, so the card can't be approved after the fact.
        state.queries.forEach((query) => {
          query.tool_calls?.forEach((call) => {
            if (isWaitingOnUser([call])) {
              call.status = 'denied';
              call.not_run = 'moved_on';
            }
          });
        });
      })
      .addCase(fetchAnswer.rejected, (state, action) => {
        if (action.meta.aborted) {
          state.status = 'idle';
          return;
        }
        state.status = 'failed';
        if (state.queries.length > 0) {
          // Indexed sends (edit/retry) must fail on their own row, not
          // whatever happens to be last.
          const indx = action.meta.arg?.indx;
          const targetIndex =
            indx !== undefined && indx >= 0 && indx < state.queries.length
              ? indx
              : state.queries.length - 1;
          state.queries[targetIndex].error = 'Something went wrong';
        }
      });
  },
});

export const selectQueries = (state: RootState) => state.conversation.queries;

export const selectStatus = (state: RootState) => state.conversation.status;

export const {
  addQuery,
  updateQuery,
  resendQuery,
  updateStreamingQuery,
  updateConversationId,
  updateThought,
  updateStreamingSource,
  updateToolCall,
  setWorkflowRunId,
  updateResearchPlan,
  updateResearchProgress,
  setConversation,
  setConversationId,
  setStatus,
  raiseError,
  raiseNotice,
  retractResponse,
  resetConversation,
  applyMessageTail,
  updateMessageMeta,
} = conversationSlice.actions;
export default conversationSlice.reducer;

// Listener (not a reducer) so a scheduled message appended to the open
// chat can dispatch loadConversation + sidebar refresh.
/** How long a continuation that landed mid-stream waits for the stream to end. */
export const CONTINUATION_REFRESH_WAIT_MS = 10 * 60 * 1000;

export const conversationListenerMiddleware = createListenerMiddleware();

let listRefresh: Promise<void> | null = null;
let listRefreshAgain = false;

/**
 * Refresh the sidebar list for an event or an answer's end, one fetch at a
 * time. A refresh asked for while one runs folds into a single follow-up
 * fetch, so a burst of events (a replayed backlog, several chats finishing)
 * costs two requests and an older list never lands over a newer one; a
 * `conversation.renamed` that arrives meanwhile gets a list read after the
 * title. A failed fetch keeps the list on screen.
 *
 * Args:
 *   getState: The store's state getter; the token is read at each fetch.
 *   dispatch: The store's dispatch.
 *
 * Returns:
 *   A promise that settles once the list is current, follow-up included.
 */
function refreshConversationList(
  getState: () => unknown,
  dispatch: (action: ReturnType<typeof receiveConversations>) => unknown,
): Promise<void> {
  if (listRefresh) {
    listRefreshAgain = true;
    return listRefresh;
  }
  listRefresh = (async () => {
    try {
      do {
        listRefreshAgain = false;
        const { token } = (getState() as RootState).preference;
        try {
          const fetched = await getConversations(token);
          if (fetched.data) dispatch(receiveConversations(fetched));
        } catch (error) {
          console.error('conversations refresh failed', error);
        }
      } while (listRefreshAgain);
    } finally {
      listRefresh = null;
    }
  })();
  return listRefresh;
}

conversationListenerMiddleware.startListening({
  actionCreator: sseEventReceived,
  effect: async (action: PayloadAction<SSEEvent>, listenerApi) => {
    const envelope = action.payload;
    // A one-time scheduled run, or a continuation turn after a background
    // job (or a monitor, a trigger or an approval) woke the agent.
    if (
      envelope.type !== 'schedule.message.appended' &&
      envelope.type !== 'conversation.continued'
    )
      return;
    const payload = (envelope.payload || {}) as Record<string, unknown>;
    const conversationId =
      (payload.conversation_id as string | undefined) || '';
    if (!conversationId) return;

    const state = listenerApi.getState() as RootState;

    // Skip mid-stream: loadConversation -> updateConversationId flips status
    // to 'idle', and the next SSE chunk dies on the 'idle' guard in
    // updateStreamingQuery. Defer the refresh to the user's next navigation.
    const streamingHere =
      state.conversation.conversationId === conversationId &&
      state.conversation.status === 'loading';
    if (
      state.conversation.conversationId === conversationId &&
      state.conversation.status !== 'loading'
    ) {
      listenerApi.dispatch(
        loadConversation({ id: conversationId, force: true }),
      );
    }

    // Refresh sidebar; server reorders by updated_at which just bumped.
    await refreshConversationList(listenerApi.getState, listenerApi.dispatch);

    // A continuation that landed while the user's own answer streamed shows
    // once that stream ends, if the chat is still open.
    if (streamingHere && envelope.type === 'conversation.continued') {
      const ended = await listenerApi.condition(
        (_, current) =>
          (current as RootState).conversation.status !== 'loading',
        CONTINUATION_REFRESH_WAIT_MS,
      );
      const after = listenerApi.getState() as RootState;
      if (ended && after.conversation.conversationId === conversationId) {
        listenerApi.dispatch(
          loadConversation({ id: conversationId, force: true }),
        );
      }
    }
  },
});

// A turn this chat shows waiting on an approval was moved past in another tab
// (or the request expired): reload it so the card becomes the call that never
// ran. Never mid-stream: a reload then would drop the stream's later chunks,
// so it waits for the stream (or a tail that may still hold the old turn) to end.
conversationListenerMiddleware.startListening({
  actionCreator: sseEventReceived,
  effect: async (action: PayloadAction<SSEEvent>, listenerApi) => {
    const envelope = action.payload;
    if (envelope.type !== 'tool.approval.cleared') return;
    const payload = (envelope.payload || {}) as Record<string, unknown>;
    if (!APPROVAL_RETIRED_REASONS.has(String(payload.reason ?? ''))) return;
    const conversationId =
      (payload.conversation_id as string | undefined) || envelope.scope?.id;
    const state = listenerApi.getState() as RootState;
    if (!conversationId || state.conversation.conversationId !== conversationId)
      return;
    if (state.conversation.status === 'loading') {
      const ended = await listenerApi.condition(
        (_, current) =>
          (current as RootState).conversation.status !== 'loading',
        CONTINUATION_REFRESH_WAIT_MS,
      );
      const after = listenerApi.getState() as RootState;
      if (!ended || after.conversation.conversationId !== conversationId)
        return;
    }
    listenerApi.dispatch(loadConversation({ id: conversationId, force: true }));
  },
});

// A new chat is on the server, named after its question, from its answer's
// first event: list it in the sidebar then, so it shows with its working mark
// while it answers, not only once the answer ends. This tab's stream names it
// (setConversationId); a chat started in another tab arrives as
// `message.started`. One list refresh per chat, whichever comes first.
const listingConversations = new Set<string>();

async function listNewConversation(
  conversationId: string,
  getState: () => unknown,
  dispatch: (action: ReturnType<typeof receiveConversations>) => unknown,
): Promise<void> {
  const state = getState() as RootState;
  const listed = state.preference.conversations.data?.some(
    (chat) => chat.id === conversationId,
  );
  if (listed || listingConversations.has(conversationId)) return;
  listingConversations.add(conversationId);
  try {
    await refreshConversationList(getState, dispatch);
  } finally {
    listingConversations.delete(conversationId);
  }
}

conversationListenerMiddleware.startListening({
  actionCreator: conversationSlice.actions.setConversationId,
  effect: async (action, listenerApi) => {
    if (!action.payload) return;
    await listNewConversation(
      action.payload,
      listenerApi.getState,
      listenerApi.dispatch,
    );
  },
});

conversationListenerMiddleware.startListening({
  actionCreator: sseEventReceived,
  effect: async (action: PayloadAction<SSEEvent>, listenerApi) => {
    const envelope = action.payload;
    const payload = (envelope.payload || {}) as Record<string, unknown>;
    const conversationId = String(payload.conversation_id ?? '');
    if (!conversationId) return;
    if (envelope.type === 'message.started') {
      // An answer this tab is not streaming started in the chat it shows: a
      // continuation after a background job, or a turn from another tab.
      // Loading the chat picks its in-flight message up and tails it, so it
      // streams here and can be stopped. Never mid-stream (see above).
      const state = listenerApi.getState() as RootState;
      const messageId = String(payload.message_id ?? '');
      if (
        messageId &&
        state.conversation.conversationId === conversationId &&
        state.conversation.status !== 'loading' &&
        !state.conversation.queries.some(
          (query) => query.messageId === messageId,
        )
      ) {
        listenerApi.dispatch(
          loadConversation({
            id: conversationId,
            force: true,
            unlessStreaming: true,
          }),
        );
      }
      await listNewConversation(
        conversationId,
        listenerApi.getState,
        listenerApi.dispatch,
      );
    } else if (envelope.type === 'message.finished') {
      // An answer that ended while the user was elsewhere is marked unread
      // on the server; refresh the list for its mark. The chat this tab
      // shows needs none while the user looks at it: nothing was marked.
      // Unwatched, it may have been, by an answer from another tab or device
      // that this tab never streamed. "Shows" is what presence reports (the
      // route), not the last chat in state: on /settings that one is unwatched.
      const state = listenerApi.getState() as RootState;
      const shown = shownConversationId(
        typeof window === 'undefined' ? '/' : window.location.pathname,
        state.conversation.conversationId,
        state.conversation.status === 'loading',
      );
      if (shown === conversationId && isPageAttended()) return;
      await refreshConversationList(listenerApi.getState, listenerApi.dispatch);
    } else if (envelope.type === 'conversation.renamed') {
      // The generated title, saved after the answer ended. It replaces the
      // question-prefix name it names as `previous`: a chat the user renamed
      // meanwhile (an event replayed after the stream dropped) keeps its
      // name. A chat not listed yet, or a list fetch that read before the
      // title, gets a list that holds it.
      const name = String(payload.name ?? '');
      if (!name) return;
      const previous =
        typeof payload.previous === 'string' ? payload.previous : null;
      const chat = (
        listenerApi.getState() as RootState
      ).preference.conversations.data?.find((c) => c.id === conversationId);
      if (chat && (previous === null || chat.name === previous)) {
        listenerApi.dispatch(renameConversation({ id: conversationId, name }));
      }
      if (!chat || listRefresh) {
        await refreshConversationList(
          listenerApi.getState,
          listenerApi.dispatch,
        );
      }
    }
  },
});
