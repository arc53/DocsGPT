import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { fetchAnswerApi } from './conversationApi';
import { ConversationState, Query } from './conversationModels';
import { Dispatch } from 'react';

const initialState: ConversationState = {
  queries: [],
  status: 'idle',
};

export const fetchAnswer = createAsyncThunk<
  void,
  { question: string },
  { dispatch: Dispatch; state: RootState }
>('fetchAnswer', ({ question }, { dispatch, getState }) => {
  const state = getState();

  fetchAnswerApi(
    question,
    state.preference.apiKey,
    state.preference.selectedDocs!,
    (event) => {
      const data = JSON.parse(event.data);
      console.log(data);

      // check if the 'end' event has been received
      if (data.type === 'end') {
        // set status to 'idle'
        dispatch(conversationSlice.actions.setStatus('idle'));
      } else {
        const result = JSON.stringify(data.answer);
        dispatch(
          updateQuery({
            index: state.conversation.queries.length - 1,
            query: { response: result },
          }),
        );
      }
    },
  );
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
    setStatus(state, action: PayloadAction<string>) {
      state.status = action.payload;
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
