import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { getConversations } from '../preferences/preferenceApi';
import { setConversations } from '../preferences/preferenceSlice';
import store from '../store';
import {
  clearAttachments,
  selectCompletedAttachments,
} from '../upload/uploadSlice';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
} from './conversationHandlers';
import { Answer, ConversationState, Query, Status } from './conversationModels';
import { ToolCallsType } from './types';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
};

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';

let abortController: AbortController | null = null;
export function handleAbort() {
  if (abortController) {
    abortController.abort();
    abortController = null;
  }
}

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

  const currentConversationId = state.conversation.conversationId;

  if (state.preference) {
    if (API_STREAMING) {
      await handleFetchAnswerSteaming(
        question,
        signal,
        state.preference.token,
        state.preference.selectedDocs!,
        currentConversationId,
        state.preference.prompt.id,
        state.preference.chunks,
        state.preference.token_limit,
        (event) => {
          const data = JSON.parse(event.data);
          const targetIndex = indx ?? state.conversation.queries.length - 1;

          // Only process events if they match the current conversation
          if (currentConversationId === state.conversation.conversationId) {
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
              // Only update the conversationId if it's currently null
              const currentState = getState() as RootState;
              if (currentState.conversation.conversationId === null) {
                dispatch(
                  updateConversationId({
                    query: { conversationId: data.id },
                  }),
                );
              }
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
        true, // Always save conversation
      );
    } else {
      const answer = await handleFetchAnswer(
        question,
        signal,
        state.preference.token,
        state.preference.selectedDocs!,
        state.conversation.conversationId,
        state.preference.prompt.id,
        state.preference.chunks,
        state.preference.token_limit,
        state.preference.selectedAgent?.id,
        attachmentIds,
        true, // Always save conversation
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
      action: PayloadAction<{ index: number; prompt: string; query?: Query }>,
    ) {
      state.queries = [
        ...state.queries.splice(0, action.payload.index),
        action.payload,
      ];
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
    },
    updateConversationId(
      state,
      action: PayloadAction<{ query: Partial<Query> }>,
    ) {
      state.conversationId = action.payload.query.conversationId ?? null;
      state.status = 'idle';
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
          return state;
        }
        state.status = 'failed';
        state.queries[state.queries.length - 1].error = 'Something went wrong';
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
  setConversation,
  setStatus,
  raiseError,
  resetConversation,
} = conversationSlice.actions;
export default conversationSlice.reducer;
