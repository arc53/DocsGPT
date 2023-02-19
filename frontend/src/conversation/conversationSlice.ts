import { createSlice } from '@reduxjs/toolkit';

type MESSAGE_TYPE = 'QUESTION' | 'ANSWER';

interface SingleConversation {
  message: string;
  messageType: MESSAGE_TYPE;
}

interface ConversationState {
  conversation: SingleConversation[];
}

const initialState: ConversationState = {
  conversation: [],
};

export const conversationSlice = createSlice({
  name: 'conversation',
  initialState,
  reducers: {
    addMessage(state, action) {
      state.conversation.push(action.payload);
    },
  },
});

export const { addMessage } = conversationSlice.actions;
export default conversationSlice.reducer;
