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
          (event) => {
            const data = JSON.parse(event.data);

            // check if the 'end' event has been received
            if (data.type === 'end') {
              // set status to 'idle'
              dispatch(conversationSlice.actions.setStatus('idle'));
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
          dispatch(
            updateQuery({
              index: state.conversation.queries.length - 1,
              query: { response: answer.answer },
            }),
          );
          dispatch(conversationSlice.actions.setStatus('idle'));
        }
      }
    }
    return { answer: '', query: question, result: '' };
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

export const { addQuery, updateQuery, updateStreamingQuery } =
  conversationSlice.actions;
export default conversationSlice.reducer;
