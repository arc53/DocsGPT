import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { Query, Status, Answer } from '../conversation/conversationModels';
import { createAsyncThunk } from '@reduxjs/toolkit';
import {
  handleFetchSharedAnswer,
  handleFetchSharedAnswerStreaming,
} from './conversationHandlers';

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';
interface SharedConversationsType {
  queries: Query[];
  apiKey?: string;
  identifier: string;
  status: Status;
  date?: string;
  title?: string;
}

const initialState: SharedConversationsType = {
  queries: [],
  identifier: '',
  status: 'idle',
};

export const fetchSharedAnswer = createAsyncThunk<Answer, { question: string }>(
  'shared/fetchAnswer',
  async ({ question }, { dispatch, getState, signal }) => {
    const state = getState() as RootState;

    if (state.preference && state.sharedConversation.apiKey) {
      if (API_STREAMING) {
        await handleFetchSharedAnswerStreaming(
          question,
          signal,
          state.sharedConversation.apiKey,
          state.sharedConversation.queries,

          (event) => {
            const data = JSON.parse(event.data);
            // check if the 'end' event has been received
            if (data.type === 'end') {
              // set status to 'idle'
              dispatch(sharedConversationSlice.actions.setStatus('idle'));
              dispatch(saveToLocalStorage());
            } else if (data.type === 'source') {
              dispatch(
                updateStreamingSource({
                  index: state.sharedConversation.queries.length - 1,
                  query: { sources: data.source ?? [] },
                }),
              );
            } else if (data.type === 'error') {
              // set status to 'failed'
              dispatch(sharedConversationSlice.actions.setStatus('failed'));
              dispatch(
                sharedConversationSlice.actions.raiseError({
                  index: state.conversation.queries.length - 1,
                  message: data.error,
                }),
              );
            } else {
              const result = data.answer;
              dispatch(
                updateStreamingQuery({
                  index: state.sharedConversation.queries.length - 1,
                  query: { response: result },
                }),
              );
            }
          },
        );
      } else {
        const answer = await handleFetchSharedAnswer(
          question,
          signal,
          state.sharedConversation.apiKey,
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
              index: state.sharedConversation.queries.length - 1,
              query: { response: answer.answer, sources: sourcesPrepped },
            }),
          );
          dispatch(sharedConversationSlice.actions.setStatus('idle'));
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

export const sharedConversationSlice = createSlice({
  name: 'sharedConversation',
  initialState,
  reducers: {
    setStatus(state, action: PayloadAction<Status>) {
      state.status = action.payload;
    },
    setIdentifier(state, action: PayloadAction<string>) {
      state.identifier = action.payload;
    },
    setFetchedData(
      state,
      action: PayloadAction<{
        queries: Query[];
        title: string;
        date: string;
        identifier: string;
      }>,
    ) {
      const { queries, title, identifier, date } = action.payload;
      const previousQueriesStr = localStorage.getItem(identifier);
      const localySavedQueries: Query[] = previousQueriesStr
        ? JSON.parse(previousQueriesStr)
        : [];
      state.queries = [...queries, ...localySavedQueries];
      state.title = title;
      state.date = date;
      state.identifier = identifier;
    },
    setClientApiKey(state, action: PayloadAction<string>) {
      state.apiKey = action.payload;
    },
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
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
    updateStreamingSource(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const { index, query } = action.payload;
      if (!state.queries[index].sources) {
        state.queries[index].sources = query.sources ?? [];
      } else if (query.sources && query.sources.length > 0) {
        state.queries[index].sources = [
          ...(state.queries[index].sources ?? []),
          ...query.sources,
        ];
      }
    },
    raiseError(
      state,
      action: PayloadAction<{ index: number; message: string }>,
    ) {
      const { index, message } = action.payload;
      state.queries[index].error = message;
    },
    saveToLocalStorage(state) {
      const previousQueriesStr = localStorage.getItem(state.identifier);
      previousQueriesStr
        ? localStorage.setItem(
            state.identifier,
            JSON.stringify([
              ...JSON.parse(previousQueriesStr),
              state.queries[state.queries.length - 1],
            ]),
          )
        : localStorage.setItem(
            state.identifier,
            JSON.stringify([state.queries[state.queries.length - 1]]),
          );
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchSharedAnswer.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchSharedAnswer.rejected, (state, action) => {
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

export const {
  setStatus,
  setIdentifier,
  setFetchedData,
  setClientApiKey,
  updateQuery,
  updateStreamingQuery,
  addQuery,
  saveToLocalStorage,
  updateStreamingSource,
} = sharedConversationSlice.actions;

export const selectStatus = (state: RootState) =>
  state.sharedConversation.status;
export const selectClientAPIKey = (state: RootState) =>
  state.sharedConversation.apiKey;
export const selectQueries = (state: RootState) =>
  state.sharedConversation.queries;
export const selectTitle = (state: RootState) => state.sharedConversation.title;
export const selectDate = (state: RootState) => state.sharedConversation.date;

type RootState = ReturnType<typeof store.getState>;

sharedConversationSlice;
export default sharedConversationSlice.reducer;
