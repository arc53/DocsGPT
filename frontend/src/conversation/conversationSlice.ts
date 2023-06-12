import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { fetchAnswerApi, fetchAnswerSteaming } from './conversationApi';
import { Answer, ConversationState, Query, Status } from './conversationModels';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
};

const API_STREAMING = import.meta.env.VITE_API_STREAMING === 'true';

export const fetchAnswer = createAsyncThunk<Answer, { question: string }>(
  'fetchAnswer',
  async ({ question }, { dispatch, getState }) => {
    const state = getState() as RootState;
    if (state.preference) {
      if (API_STREAMING) {
        await fetchAnswerSteaming(
          question,
          state.preference.apiKey,
          state.preference.selectedDocs!,
          state.conversation.queries,
          (event) => {
            const data = JSON.parse(event.data);

            // check if the 'end' event has been received
            if (data.type === 'end') {
              // set status to 'idle'
              dispatch(conversationSlice.actions.setStatus('idle'));
            } else if (data.type === 'source') {
              // check if data.metadata exists
              let result;
              if (data.metadata && data.metadata.title) {
                const titleParts = data.metadata.title.split('/');
                result = {
                  title: titleParts[titleParts.length - 1],
                  text: data.doc,
                };
              } else {
                result = { title: data.doc, text: data.doc };
              }
              dispatch(
                updateStreamingSource({
                  index: state.conversation.queries.length - 1,
                  query: { sources: [result] },
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
        const answer = await fetchAnswerApi(
          question,
          state.preference.apiKey,
          state.preference.selectedDocs!,
          state.conversation.queries,
        );
        if (answer) {
          let sourcesPrepped = [];
          sourcesPrepped = answer.sources.map((source) => {
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
          dispatch(conversationSlice.actions.setStatus('idle'));
        }
      }
    }
    return { answer: '', query: question, result: '', sources: [] };
  },
);

export const conversationSlice = createSlice({
  name: 'conversation',
  initialState,
  reducers: {
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
    },
    updateStreamingQuery(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const index = action.payload.index;
      if (action.payload.query.response) {
        state.queries[index].response =
          (state.queries[index].response || '') + action.payload.query.response;
      } else {
        state.queries[index] = {
          ...state.queries[index],
          ...action.payload.query,
        };
      }
    },
    updateStreamingSource(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const index = action.payload.index;
      if (!state.queries[index].sources) {
        state.queries[index].sources = [action.payload.query.sources![0]];
      } else {
        state.queries[index].sources!.push(action.payload.query.sources![0]);
      }
    },
    updateQuery(
      state,
      action: PayloadAction<{ index: number; query: Partial<Query> }>,
    ) {
      const index = action.payload.index;
      state.queries[index] = {
        ...state.queries[index],
        ...action.payload.query,
      };
    },
    setStatus(state, action: PayloadAction<Status>) {
      state.status = action.payload;
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchAnswer.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchAnswer.rejected, (state, action) => {
        state.status = 'failed';
        state.queries[state.queries.length - 1].error =
          'Something went wrong. Please try again later.';
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
  updateStreamingSource,
} = conversationSlice.actions;
export default conversationSlice.reducer;
