import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { getConversations } from '../preferences/preferenceApi';
import { setConversations } from '../preferences/preferenceSlice';
import store from '../store';
import {
  handleFetchAnswer,
  handleFetchAnswerSteaming,
  handleSearch,
} from './conversationHandlers';
import { Answer, ConversationState, Query, Status } from './conversationModels';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
  conversationId: null,
};

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';

export const fetchAnswer = createAsyncThunk<Answer, { question: string }>(
  'fetchAnswer',
  async ({ question }, { dispatch, getState, signal }) => {
    const state = getState() as RootState;
    if (state.preference) {
      if (API_STREAMING) {
        await handleFetchAnswerSteaming(
          question,
          signal,
          state.preference.selectedDocs!,
          state.conversation.queries,
          state.conversation.conversationId,
          state.preference.prompt.id,
          state.preference.chunks,
          state.preference.token_limit,

          (event) => {
            const data = JSON.parse(event.data);

            // check if the 'end' event has been received
            if (data.type === 'end') {
              // set status to 'idle'
              dispatch(conversationSlice.actions.setStatus('idle'));
              getConversations()
                .then((fetchedConversations) => {
                  dispatch(setConversations(fetchedConversations));
                })
                .catch((error) => {
                  console.error('Failed to fetch conversations: ', error);
                });

              handleSearch(
                //search for sources post streaming
                question,
                state.preference.selectedDocs!,
                state.conversation.conversationId,
                state.conversation.queries,
                state.preference.chunks,
                state.preference.token_limit,
              ).then((sources) => {
                //dispatch streaming sources
                dispatch(
                  updateStreamingSource({
                    index: state.conversation.queries.length - 1,
                    query: { sources: sources ?? [] },
                  }),
                );
              });
            } else if (data.type === 'id') {
              dispatch(
                updateConversationId({
                  query: { conversationId: data.id },
                }),
              );
              handleSearch(
                //search for sources post streaming
                question,
                state.preference.selectedDocs!,
                state.conversation.conversationId,
                state.conversation.queries,
                state.preference.chunks,
                state.preference.token_limit,
              ).then((sources) => {
                //dispatch streaming sources
                dispatch(
                  updateStreamingSource({
                    index: state.conversation.queries.length - 1,
                    query: { sources: sources ?? [] },
                  }),
                );
              });
            } else if (data.type === 'error') {
              // set status to 'failed'
              dispatch(conversationSlice.actions.setStatus('failed'));
              dispatch(
                conversationSlice.actions.raiseError({
                  index: state.conversation.queries.length - 1,
                  message: data.error,
                }),
              );
            } else {
              const result = data.answer;
              dispatch(
                updateStreamingQuery({
                  index: state.conversation.queries.length - 1,
                  query: { response: result },
                }),
              );
            }
          },
        );
      } else {
        const answer = await handleFetchAnswer(
          question,
          signal,
          state.preference.selectedDocs!,
          state.conversation.queries,
          state.conversation.conversationId,
          state.preference.prompt.id,
          state.preference.chunks,
          state.preference.token_limit,
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
              index: state.conversation.queries.length - 1,
              query: { response: answer.answer, sources: sourcesPrepped },
            }),
          );
          dispatch(
            updateConversationId({
              query: { conversationId: answer.conversationId },
            }),
          );
          dispatch(conversationSlice.actions.setStatus('idle'));
          getConversations()
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
      sources: [],
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
    updateStreamingQuery(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
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
        state.queries[state.queries.length - 1].error =
          'Something went wrong. Please check your internet connection.';
      });
  },
});

type RootState = ReturnType<typeof store.getState>;

export const selectQueries = (state: RootState) => state.conversation.queries;

export const selectStatus = (state: RootState) => state.conversation.status;

export const {
  addQuery,
  updateQuery,
  updateStreamingQuery,
  updateConversationId,
  updateStreamingSource,
  setConversation,
} = conversationSlice.actions;
export default conversationSlice.reducer;
