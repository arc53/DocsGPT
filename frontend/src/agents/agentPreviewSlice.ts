import { envVar } from '@/env';
import {
  createAsyncThunk,
  createSlice,
  type Dispatch,
  PayloadAction,
} from '@reduxjs/toolkit';

import {
  appendAnswerText,
  appendThoughtText,
  recordToolCall,
} from '../conversation/answerSegments';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
  handleSubmitToolActions,
} from '../conversation/conversationHandlers';
import {
  Answer,
  ConversationState,
  Query,
  Status,
} from '../conversation/conversationModels';
import {
  type ErrorParams,
  readStreamError,
  setErrorDetail,
} from '../conversation/curatedError';
import {
  answeredCall,
  type QuestionAction,
} from '../conversation/questionCall';
import { NOT_PENDING_CODE } from '../conversation/conversationSlice';
import store from '../store';
import {
  clearAttachments,
  selectSendableAttachmentIds,
} from '../upload/uploadSlice';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
};

const API_STREAMING = envVar('VITE_API_STREAMING') === 'true';

let abortController: AbortController | null = null;
export function handlePreviewAbort() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

export const fetchPreviewAnswer = createAsyncThunk<
  Answer,
  { question: string; indx?: number }
>(
  'agentPreview/fetchAnswer',
  async ({ question, indx }, { dispatch, getState }) => {
    if (abortController) abortController.abort();
    abortController = new AbortController();
    const { signal } = abortController;

    const state = getState() as RootState;
    const attachmentIds = selectSendableAttachmentIds(state);

    if (attachmentIds.length > 0) {
      dispatch(clearAttachments());
    }

    if (state.preference) {
      const modelId =
        state.preference.selectedAgent?.default_model_id ||
        state.preference.selectedModel?.id;

      if (API_STREAMING) {
        await handleFetchAnswerSteaming(
          question,
          signal,
          state.preference.token,
          state.preference.selectedDocs,
          null, // No conversation ID for previews
          state.preference.prompt.id,
          state.preference.chunks,
          previewEventHandler(
            dispatch,
            indx ?? state.agentPreview.queries.length - 1,
          ),
          indx,
          state.preference.selectedAgent?.id,
          attachmentIds,
          false,
          modelId,
        );
      } else {
        const answer = await handleFetchAnswer(
          question,
          signal,
          state.preference.token,
          state.preference.selectedDocs,
          null,
          state.preference.prompt.id,
          state.preference.chunks,
          state.preference.selectedAgent?.id,
          attachmentIds,
          false,
          modelId,
        );

        if (answer) {
          const sourcesPrepped = answer.sources.map(
            (source: { title: string }) => {
              if (source && source.title) {
                const titleParts = source.title.split('/');
                return {
                  ...source,
                  title: titleParts[titleParts.length - 1],
                };
              }
              return source;
            },
          );

          const targetIndex = indx ?? state.agentPreview.queries.length - 1;

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
          dispatch(agentPreviewSlice.actions.setStatus('idle'));
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
  },
);

/**
 * Applies one event of a preview stream (a new turn, or a turn resumed with
 * the answers to its questions) to the turn at ``targetIndex``.
 */
function previewEventHandler(
  dispatch: Dispatch,
  targetIndex: number,
): (event: MessageEvent) => void {
  return (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'end') {
      dispatch(agentPreviewSlice.actions.setStatus('idle'));
    } else if (data.type === 'id') {
      // Each preview turn is its own hidden conversation; a turn paused on
      // questions resumes in it.
      if (data.id)
        dispatch(
          updateQuery({
            index: targetIndex,
            query: { conversationId: data.id },
          }),
        );
    } else if (data.type === 'thought') {
      dispatch(
        updateThought({
          index: targetIndex,
          query: { thought: data.thought },
        }),
      );
    } else if (data.type === 'source') {
      dispatch(
        updateStreamingSource({
          index: targetIndex,
          query: { sources: data.source ?? [] },
        }),
      );
    } else if (data.type === 'tool_call') {
      dispatch(
        updateToolCall({
          index: targetIndex,
          tool_call: data.data,
        }),
      );
    } else if (data.type === 'tool_calls_pending') {
      // Nothing generates while the turn waits for the user.
      dispatch(agentPreviewSlice.actions.setStatus('awaiting_tool_actions'));
    } else if (data.type === 'error') {
      dispatch(agentPreviewSlice.actions.setStatus('failed'));
      dispatch(
        agentPreviewSlice.actions.raiseError({
          index: targetIndex,
          ...readStreamError(data),
        }),
      );
    } else if (data.type === 'structured_answer') {
      dispatch(
        updateStreamingQuery({
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
          index: targetIndex,
          query: { response: data.answer },
        }),
      );
    }
  };
}

/**
 * Resume a preview turn paused on clarifying questions (`ask_user`) with the
 * answers, or with Just answer, in the turn's own conversation.
 */
export const resumePreviewQuestion = createAsyncThunk<
  void,
  { callId: string; action: QuestionAction }
>(
  'agentPreview/resumeQuestion',
  async ({ callId, action }, { dispatch, getState }) => {
    const state = getState() as RootState;
    const { queries } = state.agentPreview;
    const index = queries.findIndex((query) =>
      query.tool_calls?.some((call) => call.call_id === callId),
    );
    const call = queries[index]?.tool_calls?.find(
      (candidate) => candidate.call_id === callId,
    );
    const conversationId = queries[index]?.conversationId;
    if (!call || !conversationId) return;

    if (abortController) abortController.abort();
    abortController = new AbortController();
    const { signal } = abortController;

    // A refused try left its error on the turn; this answer is the retry.
    if (queries[index].error)
      dispatch(
        updateQuery({
          index,
          query: {
            error: undefined,
            errorCode: undefined,
            errorParams: undefined,
          },
        }),
      );
    dispatch(updateToolCall({ index, tool_call: answeredCall(call, action) }));
    dispatch(agentPreviewSlice.actions.setStatus('loading'));
    // The first frame tells whether the server took the answers; a refusal
    // (or a request that never got there) left the turn waiting, so the
    // cards come back as they were for another try.
    let taken: boolean | null = null;
    const onEvent = previewEventHandler(dispatch, index);
    const restore = () =>
      dispatch(updateToolCall({ index, tool_call: { ...call } }));
    try {
      await handleSubmitToolActions(
        conversationId,
        [{ call_id: callId, ...action }],
        state.preference.token,
        signal,
        (event) => {
          if (taken === null) {
            const data = JSON.parse(event.data);
            taken = data.type !== 'error' || data.code === NOT_PENDING_CODE;
          }
          onEvent(event);
        },
      );
    } catch (error) {
      if (taken !== true && !signal.aborted) restore();
      throw error;
    }
    if (taken === false) restore();
  },
);

export const agentPreviewSlice = createSlice({
  name: 'agentPreview',
  initialState,
  reducers: {
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
    },
    resendQuery(
      state,
      action: PayloadAction<{ index: number; prompt: string }>,
    ) {
      const { index, prompt } = action.payload;
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
    },
    updateStreamingQuery(
      state,
      action: PayloadAction<{
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (state.status === 'idle') return;

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
    updateThought(
      state,
      action: PayloadAction<{
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
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
        index: number;
        query: Partial<Query>;
      }>,
    ) {
      const { index, query } = action.payload;
      if (!state.queries[index].sources) {
        state.queries[index].sources = query?.sources;
      } else if (query.sources) {
        state.queries[index].sources!.push(...query.sources);
      }
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
    raiseError(
      state,
      action: PayloadAction<{
        index: number;
        message: string;
        /** Why the turn failed (``context_length_exceeded``), when known. */
        code?: string;
        /** The values a curated error was worded from. */
        params?: ErrorParams;
      }>,
    ) {
      const { index, message, code, params } = action.payload;
      state.queries[index].error = message;
      setErrorDetail(state.queries[index], code, params);
    },
    resetPreview: (state) => {
      state.queries = initialState.queries;
      state.status = initialState.status;
      state.conversationId = initialState.conversationId;
      handlePreviewAbort();
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchPreviewAnswer.pending, (state) => {
        state.status = 'loading';
        // A new message moves past questions still waiting for an answer.
        state.queries.forEach((query) => {
          query.tool_calls?.forEach((call) => {
            if (call.status === 'awaiting_answer') {
              call.status = 'denied';
              call.not_run = 'moved_on';
            }
          });
        });
      })
      .addCase(resumePreviewQuestion.rejected, (state, action) => {
        state.status = action.meta.aborted ? 'idle' : 'failed';
      })
      .addCase(fetchPreviewAnswer.rejected, (state, action) => {
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

export const selectPreviewQueries = (state: RootState) =>
  state.agentPreview.queries;
export const selectPreviewStatus = (state: RootState) =>
  state.agentPreview.status;

export const {
  addQuery,
  updateQuery,
  resendQuery,
  updateStreamingQuery,
  updateThought,
  updateStreamingSource,
  updateToolCall,
  setStatus,
  raiseError,
  resetPreview,
} = agentPreviewSlice.actions;

export default agentPreviewSlice.reducer;
