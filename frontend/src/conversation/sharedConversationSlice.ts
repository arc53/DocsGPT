import { createSlice } from '@reduxjs/toolkit';
import type { PayloadAction } from '@reduxjs/toolkit';
import store from '../store';
import { Query, Status } from '../conversation/conversationModels';

interface SharedConversationsType {
  queries: Query[];
  apiKey?: string;
  identifier: string | null;
  status: Status;
  date?: string;
  title?: string;
}

const initialState: SharedConversationsType = {
  queries: [],
  identifier: null,
  status: 'idle',
};

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
      state.queries = queries;
      state.title = title;
      state.date = date;
      state.identifier = identifier;
    },
    setClientApiKey(state, action: PayloadAction<string>) {
      state.apiKey = action.payload;
    },
  },
});

export const { setStatus, setIdentifier, setFetchedData, setClientApiKey } =
  sharedConversationSlice.actions;

export const selectStatus = (state: RootState) => state.conversation.status;
export const selectClientAPIKey = (state: RootState) =>
  state.sharedConversation.apiKey;
export const selectQueries = (state: RootState) =>
  state.sharedConversation.queries;
export const selectTitle = (state: RootState) => state.sharedConversation.title;
export const selectDate = (state: RootState) => state.sharedConversation.date;

type RootState = ReturnType<typeof store.getState>;

sharedConversationSlice;
export default sharedConversationSlice.reducer;
