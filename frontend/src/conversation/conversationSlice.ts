import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { getConversations } from '../preferences/preferenceApi';
import { setConversations } from '../preferences/preferenceSlice';
import store from '../store';
import {
  selectCompletedAttachments,
  clearAttachments,
} from '../upload/uploadSlice';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
} from './conversationHandlers';
import { Answer, Query, Status, ConversationState } from './conversationModels';

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
  { question: string; indx?: number; isPreview?: boolean }
>(
  'fetchAnswer',
  async ({ question, indx, isPreview = false }, { dispatch, getState }) => {
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
    const conversationIdToSend = isPreview ? null : currentConversationId;
    const save_conversation = isPreview ? false : true;

    if (state.preference) {
      if (API_STREAMING) {
        await handleFetchAnswerSteaming(
          question,
          signal,
          state.preference.token,
          state.preference.selectedDocs!,
          state.conversation.queries,
          conversationIdToSend,
          state.preference.prompt.id,
          state.preference.chunks,
          state.preference.token_limit,
          (event) => {
            const data = JSON.parse(event.data);
            const targetIndex = indx ?? state.conversation.queries.length - 1;

            if (data.type === 'end') {
              dispatch(conversationSlice.actions.setStatus('idle'));
              if (!isPreview) {
                getConversations(state.preference.token)
                  .then((fetchedConversations) => {
                    dispatch(setConversations(fetchedConversations));
                  })
                  .catch((error) => {
                    console.error('Failed to fetch conversations: ', error);
                  });
              }
              if (!isSourceUpdated) {
                dispatch(
                  updateStreamingSource({
                    index: targetIndex,
                    query: { sources: [] },
                  }),
                );
              }
            } else if (data.type === 'id') {
              if (!isPreview) {
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
                  index: targetIndex,
                  query: { thought: result },
                }),
              );
            } else if (data.type === 'source') {
              isSourceUpdated = true;
              dispatch(
                updateStreamingSource({
                  index: targetIndex,
                  query: { sources: data.source ?? [] },
                }),
              );
            } else if (data.type === 'tool_calls') {
              dispatch(
                updateToolCalls({
                  index: targetIndex,
                  query: { tool_calls: data.tool_calls },
                }),
              );
            } else if (data.type === 'error') {
              // set status to 'failed'
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  index: targetIndex,
                  message: data.error,
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
          save_conversation,
        );
      } else {
        const answer = await handleFetchAnswer(
          question,
          signal,
          state.preference.token,
          state.preference.selectedDocs!,
          state.conversation.queries,
          state.conversation.conversationId,
          state.preference.prompt.id,
          state.preference.chunks,
          state.preference.token_limit,
          state.preference.selectedAgent?.id,
          attachmentIds,
          save_conversation,
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
          if (!isPreview) {
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
          }
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
  },
);

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
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      if (state.status === 'idle') return;
      const { index, query } = action.payload;
      if (query.response != undefined) {
        state.queries[index].response =
          (state.queries[index].response || '') + query.response;
      } else {
        state.queries[index] = {
          ...state.queries[index],
          ...query,
        };
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
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      if (query.thought != undefined) {
        state.queries[index].thought =
          (state.queries[index].thought || '') + query.thought;
      } else {
        state.queries[index] = {
          ...state.queries[index],
          ...query,
        };
      }
    },
    updateStreamingSource(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      if (!state.queries[index].sources) {
        state.queries[index].sources = query?.sources;
      } else {
        state.queries[index].sources!.push(query.sources![0]);
      }
    },
    updateToolCalls(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      state.queries[index].tool_calls = query?.tool_calls ?? [];
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
      action: PayloadAction<{ index: number; message: string }>,
    ) {
      const { index, message } = action.payload;
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
  updateToolCalls,
  setConversation,
  setStatus,
  raiseError,
  resetConversation,
} = conversationSlice.actions;
export default conversationSlice.reducer;
