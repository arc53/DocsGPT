import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import conversationService from '../api/services/conversationService';
import { getConversations } from '../preferences/preferenceApi';
import { setConversations } from '../preferences/preferenceSlice';
import store from '../store';
import {
  clearAttachments,
  selectCompletedAttachments,
} from '../upload/uploadSlice';
import { newIdempotencyKey } from '../utils/idempotency';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
  handleV1ChatCompletionStreaming,
} from './conversationHandlers';
import {
  Answer,
  ConversationState,
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
    feedback: raw?.feedback ?? undefined,
    thought: raw?.thought ?? undefined,
    sources: sources && sources.length > 0 ? sources : undefined,
    tool_calls: toolCalls && toolCalls.length > 0 ? toolCalls : undefined,
    attachments: raw?.attachments ?? undefined,
    messageId: raw?.message_id ?? undefined,
    messageStatus: status,
    requestId: raw?.request_id ?? undefined,
    lastHeartbeatAt: raw?.last_heartbeat_at ?? undefined,
  };

  if (isTerminalComplete) {
    query.response = raw?.response ?? '';
  }
  if (isFailed) {
    query.error =
      (typeof metadata.error === 'string' && metadata.error) ||
      'Generation failed before completing.';
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

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';
const USE_V1_API = import.meta.env.VITE_USE_V1_API === 'true';

let abortController: AbortController | null = null;
export function handleAbort() {
  if (abortController) {
    abortController.abort();
    abortController = null;
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

let loadSeq = 0;

export const loadConversation = createAsyncThunk<
  LoadConversationResult,
  { id: string; force?: boolean }
>('loadConversation', async ({ id, force }, { dispatch, getState }) => {
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

  // A later loadConversation has been issued; drop our writes so its
  // result wins, and tell the caller not to navigate off our return.
  if (seq !== loadSeq) {
    return { data: null, stale: true };
  }

  const mappedQueries = (data.queries || []).map(mapServerQueryToClient);
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

export const fetchAnswer = createAsyncThunk<
  Answer,
  { question: string; indx?: number }
>('fetchAnswer', async ({ question, indx }, { dispatch, getState }) => {
  if (abortController) abortController.abort();
  abortController = new AbortController();
  const { signal } = abortController;

  let isSourceUpdated = false;
  const state = getState() as RootState;
  const attachmentIds = selectCompletedAttachments(state)
    .filter((a) => a.id)
    .map((a) => a.id) as string[];

  if (attachmentIds.length > 0) {
    dispatch(clearAttachments());
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
              getConversations(state.preference.token)
                .then((fetchedConversations) => {
                  dispatch(setConversations(fetchedConversations));
                })
                .catch((error) => {
                  console.error('Failed to fetch conversations: ', error);
                });
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
            } else if (data.type === 'error') {
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  message: data.error,
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
              getConversations(state.preference.token)
                .then((fetchedConversations) => {
                  dispatch(setConversations(fetchedConversations));
                })
                .catch((error) => {
                  console.error('Failed to fetch conversations: ', error);
                });
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
            } else if (data.type === 'error') {
              // set status to 'failed'
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  conversationId: currentConversationId,
                  index: targetIndex,
                  message: data.error,
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
        getConversations(state.preference.token)
          .then((fetchedConversations) => {
            dispatch(setConversations(fetchedConversations));
          })
          .catch((error) => {
            console.error('Failed to fetch conversations: ', error);
          });
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
});

// Tail-polls the placeholder until terminal status, navigation away,
// or hard timeout. First poll fires immediately so rows that are
// already terminal resolve without delay.
const TAIL_POLL_INTERVAL_MS = 2000;
const TAIL_MAX_POLL_DURATION_MS = 10 * 60 * 1000;

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

      // 404 → row deleted (e.g. conversation wiped); bail quietly.
      if (resp.status === 404) {
        dispatch(conversationSlice.actions.setStatus('idle'));
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
      await new Promise((r) => setTimeout(r, TAIL_POLL_INTERVAL_MS));
    }
    // Hard timeout: drop status to idle so the user can interact again.
    dispatch(conversationSlice.actions.setStatus('idle'));
  },
);

export const submitToolActions = createAsyncThunk<
  void,
  {
    toolActions: {
      call_id: string;
      decision?: 'approved' | 'denied';
      comment?: string;
      result?: Record<string, any>;
    }[];
  }
>('submitToolActions', async ({ toolActions }, { dispatch, getState }) => {
  if (abortController) abortController.abort();
  abortController = new AbortController();
  const { signal } = abortController;

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
        getConversations(state.preference.token)
          .then((fetchedConversations) => {
            dispatch(setConversations(fetchedConversations));
          })
          .catch((error) => {
            console.error('Failed to fetch conversations: ', error);
          });
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
      } else if (data.type === 'error') {
        dispatch(conversationSlice.actions.setStatus('failed'));
        dispatch(
          conversationSlice.actions.raiseError({
            conversationId,
            index: targetIndex,
            message: data.error,
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
});

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
      delete state.queries[index].error;
      delete state.queries[index].structured;
      delete state.queries[index].schema;
      delete state.queries[index].feedback;
      delete state.queries[index].research;
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
      const status = tail?.status as MessageStatus | undefined;
      query.messageStatus = status;
      query.lastHeartbeatAt = tail?.last_heartbeat_at ?? query.lastHeartbeatAt;
      if (status === 'failed') {
        // Surface as error so the placeholder text never renders.
        query.error =
          (typeof tail?.error === 'string' && tail.error) ||
          'Generation failed before completing.';
        delete query.response;
        return;
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
      if (status === 'complete') {
        delete query.error;
      }
    },
    raiseError(
      state,
      action: PayloadAction<{
        conversationId: string | null;
        index: number;
        message: string;
      }>,
    ) {
      const { conversationId, index, message } = action.payload;
      if (state.conversationId !== conversationId) return;

      state.queries[index].error = message;
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
      })
      .addCase(fetchAnswer.rejected, (state, action) => {
        if (action.meta.aborted) {
          state.status = 'idle';
          return;
        }
        state.status = 'failed';
        if (state.queries.length > 0) {
          state.queries[state.queries.length - 1].error =
            'Something went wrong';
        }
      });
  },
});

type RootState = ReturnType<typeof store.getState>;

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
  updateResearchPlan,
  updateResearchProgress,
  setConversation,
  setConversationId,
  setStatus,
  raiseError,
  resetConversation,
  applyMessageTail,
  updateMessageMeta,
} = conversationSlice.actions;
export default conversationSlice.reducer;
