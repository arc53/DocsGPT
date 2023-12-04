import {
  createListenerMiddleware,
  createSlice,
  isAnyOf,
} from '@reduxjs/toolkit';
import { Doc, setLocalApiKey, setLocalRecentDocs } from './preferenceApi';
import { RootState } from '../store';

interface Preference {
  apiKey: string;
  prompt: { name: string; id: string; type: string };
  selectedDocs: Doc | null;
  sourceDocs: Doc[] | null;
  conversations: { name: string; id: string }[] | null;
}

const initialState: Preference = {
  apiKey: 'xxx',
  prompt: { name: 'default', id: 'default', type: 'public' },
  selectedDocs: {
    name: 'default',
    language: 'default',
    location: 'default',
    version: 'default',
    description: 'default',
    fullName: 'default',
    date: 'default',
    docLink: 'default',
    model: 'openai_text-embedding-ada-002',
  } as Doc,
  sourceDocs: null,
  conversations: null,
};

export const prefSlice = createSlice({
  name: 'preference',
  initialState,
  reducers: {
    setApiKey: (state, action) => {
      state.apiKey = action.payload;
    },
    setSelectedDocs: (state, action) => {
      state.selectedDocs = action.payload;
    },
    setSourceDocs: (state, action) => {
      state.sourceDocs = action.payload;
    },
    setConversations: (state, action) => {
      state.conversations = action.payload;
    },
    setPrompt: (state, action) => {
      state.prompt = action.payload;
    },
  },
});

export const {
  setApiKey,
  setSelectedDocs,
  setSourceDocs,
  setConversations,
  setPrompt,
} = prefSlice.actions;
export default prefSlice.reducer;

export const prefListenerMiddleware = createListenerMiddleware();
prefListenerMiddleware.startListening({
  matcher: isAnyOf(setApiKey),
  effect: (action, listenerApi) => {
    setLocalApiKey((listenerApi.getState() as RootState).preference.apiKey);
  },
});

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setSelectedDocs),
  effect: (action, listenerApi) => {
    setLocalRecentDocs(
      (listenerApi.getState() as RootState).preference.selectedDocs ??
        ([] as unknown as Doc),
    );
  },
});

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setPrompt),
  effect: (action, listenerApi) => {
    localStorage.setItem(
      'DocsGPTPrompt',
      JSON.stringify((listenerApi.getState() as RootState).preference.prompt),
    );
  },
});

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
export const selectSelectedDocsStatus = (state: RootState) =>
  !!state.preference.selectedDocs;
export const selectSourceDocs = (state: RootState) =>
  state.preference.sourceDocs;
export const selectSelectedDocs = (state: RootState) =>
  state.preference.selectedDocs;
export const selectConversations = (state: RootState) =>
  state.preference.conversations;
export const selectConversationId = (state: RootState) =>
  state.conversation.conversationId;
export const selectPrompt = (state: RootState) => state.preference.prompt;
