import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { fetchAnswerApi } from './conversationApi';
import { Answer, ConversationState, Query } from './conversationModels';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
};

export const fetchAnswer = createAsyncThunk<
  Answer,
  { question: string },
  { state: RootState }
>('fetchAnswer', async ({ question }, { getState }) => {
  const state = getState();

  const answer = await fetchAnswerApi(
    question,
    state.preference.apiKey,
    state.preference.selectedDocs!,
  );
  return answer;
});

export const conversationSlice = createSlice({
  name: 'conversation',
  initialState,
  reducers: {
    addQuery(state, action: PayloadAction<Query>) {
      state.queries.push(action.payload);
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
  },
  extraReducers(builder) {
    builder
      .addCase(fetchAnswer.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchAnswer.fulfilled, (state, action) => {
        state.status = 'idle';
        state.queries[state.queries.length - 1].response =
          action.payload.answer;
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

export const { addQuery, updateQuery } = conversationSlice.actions;
export default conversationSlice.reducer;
