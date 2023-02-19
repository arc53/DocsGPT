import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { ConversationState, Message } from './conversationModels';

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
    {
      text: 'ChatGPT is large learning model',
      type: 'ANSWER',
    },
  ],
};

export const conversationSlice = createSlice({
  name: 'conversation',
  initialState,
  reducers: {
    addMessage(state, action: PayloadAction<Message>) {
      state.conversation.push(action.payload);
    },
  },
});

export const { addMessage } = conversationSlice.actions;

type RootState = ReturnType<typeof store.getState>;
export const selectConversation = (state: RootState) =>
  state.conversation.conversation;

export default conversationSlice.reducer;
