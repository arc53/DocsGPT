import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
} from '../conversation/conversationHandlers';
import {
  Answer,
  ConversationState,
  Query,
  Status,
} from '../conversation/conversationModels';
import store from '../store';
import {
  clearAttachments,
  selectCompletedAttachments,
} from '../upload/uploadSlice';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
};

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';

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
    const attachmentIds = selectCompletedAttachments(state)
      .filter((a) => a.id)
      .map((a) => a.id) as string[];

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
          (event: MessageEvent) => {
            const data = JSON.parse(event.data);
            const targetIndex = indx ?? state.agentPreview.queries.length - 1;

            if (data.type === 'end') {
              dispatch(agentPreviewSlice.actions.setStatus('idle'));
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
            } else if (data.type === 'error') {
              dispatch(agentPreviewSlice.actions.setStatus('failed'));
              dispatch(
                agentPreviewSlice.actions.raiseError({
                  index: targetIndex,
                  message: data.error,
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
          },
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
      delete state.queries[index].error;
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
      }>,
    ) {
      const { index, message } = action.payload;
      state.queries[index].error = message;
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
