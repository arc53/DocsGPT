import { createAsyncThunk, createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { fetchAnswerApi } from './conversationApi';
import { Answer, ConversationState, Message } from './conversationModels';

// harcoding the initial state just for demo
const initialState: ConversationState = {
  conversation: [
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
    { text: 'what is ChatGPT', type: 'QUESTION' },
    { text: 'ChatGPT is large learning model', type: 'ANSWER' },
  ],
  status: 'idle',
};

export const fetchAnswer = createAsyncThunk<
  Answer,
  { question: string },
  { state: RootState }
>('fetchAnswer', async ({ question }, { getState }) => {
  const state = getState();
  const answer = await fetchAnswerApi(question, state.preference.apiKey);
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
      .addCase(fetchAnswer.rejected, (state) => {
        state.status = 'failed';
      });
  },
});

type RootState = ReturnType<typeof store.getState>;

export const selectConversation = (state: RootState) =>
  state.conversation.conversation;

export const selectStatus = (state: RootState) => state.conversation.status;

export const { addMessage } = conversationSlice.actions;
export default conversationSlice.reducer;
