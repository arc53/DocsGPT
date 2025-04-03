import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { getConversations } from '../preferences/preferenceApi';
import { setConversations } from '../preferences/preferenceSlice';
import store from '../store';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
} from './conversationHandlers';
import { Answer, ConversationState, Query, Status } from './conversationModels';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
  attachments: [],
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
  if (abortController) {
    abortController.abort();
  }
  abortController = new AbortController();
  const { signal } = abortController;

  let isSourceUpdated = false;
  const state = getState() as RootState;
  const attachments = state.conversation.attachments?.map(a => a.id) || [];
  
  if (state.preference) {
    if (API_STREAMING) {
      await handleFetchAnswerSteaming(
        question,
        signal,
        state.preference.token,
        state.preference.selectedDocs!,
        state.conversation.queries,
        state.conversation.conversationId,
        state.preference.prompt.id,
        state.preference.chunks,
        state.preference.token_limit,
        (event) => {
          const data = JSON.parse(event.data);

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
                  index: indx ?? state.conversation.queries.length - 1,
                  query: { sources: [] },
                }),
              );
            }
          } else if (data.type === 'id') {
            dispatch(
              updateConversationId({
                query: { conversationId: data.id },
              }),
            );
          } else if (data.type === 'thought') {
            const result = data.thought;
            console.log('thought', result);
            dispatch(
              updateThought({
                index: indx ?? state.conversation.queries.length - 1,
                query: { thought: result },
              }),
            );
          } else if (data.type === 'source') {
            isSourceUpdated = true;
            dispatch(
              updateStreamingSource({
                index: indx ?? state.conversation.queries.length - 1,
                query: { sources: data.source ?? [] },
              }),
            );
          } else if (data.type === 'tool_calls') {
            dispatch(
              updateToolCalls({
                index: indx ?? state.conversation.queries.length - 1,
                query: { tool_calls: data.tool_calls },
              }),
            );
          } else if (data.type === 'error') {
            // set status to 'failed'
            dispatch(conversationSlice.actions.setStatus('failed'));
            dispatch(
              conversationSlice.actions.raiseError({
                index: indx ?? state.conversation.queries.length - 1,
                message: data.error,
              }),
            );
          } else {
            const result = data.answer;
            dispatch(
              updateStreamingQuery({
                index: indx ?? state.conversation.queries.length - 1,
                query: { response: result },
              }),
            );
          }
        },
        indx,
        attachments
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
        attachments
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

        dispatch(
          updateQuery({
            index: indx ?? state.conversation.queries.length - 1,
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
        dispatch(conversationSlice.actions.setStatus('idle'));
        getConversations(state.preference.token)
          .then((fetchedConversations) => {
            dispatch(setConversations(fetchedConversations));
          })
          .catch((error) => {
            console.error('Failed to fetch conversations: ', error);
          });
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
      if (!state.queries[index].tool_calls) {
        state.queries[index].tool_calls = query?.tool_calls;
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
    raiseError(
      state,
      action: PayloadAction<{ index: number; message: string }>,
    ) {
      const { index, message } = action.payload;
      state.queries[index].error = message;
    },
    setAttachments: (state, action: PayloadAction<{ fileName: string; id: string }[]>) => {
      state.attachments = action.payload;
    },
    removeAttachment(state, action: PayloadAction<string>) {
      state.attachments = state.attachments?.filter(att => att.id !== action.payload);
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
  setAttachments,
  removeAttachment,
} = conversationSlice.actions;
export default conversationSlice.reducer;
