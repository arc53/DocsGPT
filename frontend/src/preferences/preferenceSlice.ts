import {
  PayloadAction,
  createListenerMiddleware,
  createSlice,
  isAnyOf,
} from '@reduxjs/toolkit';
import { setLocalApiKey, setLocalRecentDocs } from './preferenceApi';
import { RootState } from '../store';
import { ActiveState, Doc } from '../models/misc';

interface Preference {
  apiKey: string;
  prompt: { name: string; id: string; type: string };
  chunks: string;
  token_limit: number;
  selectedDocs: Doc | null;
  sourceDocs: Doc[] | null;
  conversations: { name: string; id: string }[] | null;
  modalState: ActiveState;
}

const initialState: Preference = {
  apiKey: 'xxx',
  prompt: { name: 'default', id: 'default', type: 'public' },
  chunks: '2',
  token_limit: 2000,
  selectedDocs: {
    id: 'default',
    name: 'default',
    type: 'remote',
    date: 'default',
    docLink: 'default',
    model: 'openai_text-embedding-ada-002',
    retriever: 'classic',
  } as Doc,
  sourceDocs: null,
  conversations: null,
  modalState: 'INACTIVE',
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
    setChunks: (state, action) => {
      state.chunks = action.payload;
    },
    setTokenLimit: (state, action) => {
      state.token_limit = action.payload;
    },
    setModalStateDeleteConv: (state, action: PayloadAction<ActiveState>) => {
      state.modalState = action.payload;
    },
  },
});

export const {
  setApiKey,
  setSelectedDocs,
  setSourceDocs,
  setConversations,
  setPrompt,
  setChunks,
  setTokenLimit,
  setModalStateDeleteConv,
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

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setChunks),
  effect: (action, listenerApi) => {
    localStorage.setItem(
      'DocsGPTChunks',
      JSON.stringify((listenerApi.getState() as RootState).preference.chunks),
    );
  },
});

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setTokenLimit),
  effect: (action, listenerApi) => {
    localStorage.setItem(
      'DocsGPTTokenLimit',
      JSON.stringify(
        (listenerApi.getState() as RootState).preference.token_limit,
      ),
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
export const selectModalStateDeleteConv = (state: RootState) =>
  state.preference.modalState;
export const selectSelectedDocs = (state: RootState) =>
  state.preference.selectedDocs;
export const selectConversations = (state: RootState) =>
  state.preference.conversations;
export const selectConversationId = (state: RootState) =>
  state.conversation.conversationId;
export const selectPrompt = (state: RootState) => state.preference.prompt;
export const selectChunks = (state: RootState) => state.preference.chunks;
export const selectTokenLimit = (state: RootState) =>
  state.preference.token_limit;
