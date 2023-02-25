import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { fetchAnswerApi } from './conversationApi';
import { Answer, ConversationState, Message } from './conversationModels';

const initialState: ConversationState = {
  conversation: [],
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
    addMessage(state, action: PayloadAction<Message>) {
      state.conversation.push(action.payload);
    },
  },
  extraReducers(builder) {
    builder
      .addCase(fetchAnswer.pending, (state) => {
        state.status = 'loading';
      })
      .addCase(fetchAnswer.fulfilled, (state, action) => {
        state.status = 'idle';
        state.conversation.push({
          text: action.payload.answer,
          type: 'ANSWER',
        });
      })
      .addCase(fetchAnswer.rejected, (state, action) => {
        state.status = 'failed';
        state.conversation.push({
          text: 'Something went wrong. Please try again later.',
          type: 'ERROR',
        });
      });
  },
});

type RootState = ReturnType<typeof store.getState>;

export const selectConversation = (state: RootState) =>
  state.conversation.conversation;

export const selectStatus = (state: RootState) => state.conversation.status;

export const { addMessage } = conversationSlice.actions;
export default conversationSlice.reducer;
