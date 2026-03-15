import {
  createListenerMiddleware,
  createSlice,
  isAnyOf,
  PayloadAction,
} from '@reduxjs/toolkit';

import { Agent, AgentFolder } from '../agents/types';
import { ActiveState, Doc, Prompt } from '../models/misc';
import { RootState } from '../store';
import {
  getLocalPrompt,
  getLocalRecentDocs,
  setLocalApiKey,
  setLocalRecentDocs,
} from './preferenceApi';

import type { Model } from '../models/types';
export interface Preference {
  apiKey: string;
  prompt: { name: string; id: string; type: string };
  prompts: Prompt[];
  chunks: string;
  selectedDocs: Doc[];
  sourceDocs: Doc[] | null;
  conversations: {
    data: { name: string; id: string }[] | null;
    loading: boolean;
  };
  token: string | null;
  modalState: ActiveState;
  paginatedDocuments: Doc[] | null;
  templateAgents: Agent[] | null;
  agents: Agent[] | null;
  sharedAgents: Agent[] | null;
  selectedAgent: Agent | null;
  selectedModel: Model | null;
  availableModels: Model[];
  modelsLoading: boolean;
  agentFolders: AgentFolder[] | null;
}

const initialState: Preference = {
  apiKey: 'xxx',
  prompt: { name: 'default', id: 'default', type: 'public' },
  prompts: [
    { name: 'default', id: 'default', type: 'public' },
    { name: 'creative', id: 'creative', type: 'public' },
    { name: 'strict', id: 'strict', type: 'public' },
  ],
  chunks: '2',
  selectedDocs: [
    {
      id: 'default',
      name: 'default',
      type: 'remote',
      date: 'default',
      model: 'openai_text-embedding-ada-002',
      retriever: 'classic',
    },
  ] as Doc[],
  sourceDocs: null,
  conversations: {
    data: null,
    loading: false,
  },
  token: localStorage.getItem('authToken') || null,
  modalState: 'INACTIVE',
  paginatedDocuments: null,
  templateAgents: null,
  agents: null,
  sharedAgents: null,
  selectedAgent: null,
  selectedModel: null,
  availableModels: [],
  modelsLoading: false,
  agentFolders: null,
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
    setPaginatedDocuments: (state, action) => {
      state.paginatedDocuments = action.payload;
    },
    setConversations: (state, action) => {
      state.conversations = action.payload;
    },
    setToken: (state, action) => {
      state.token = action.payload;
    },
    setPrompt: (state, action) => {
      state.prompt = action.payload;
    },
    setPrompts: (state, action: PayloadAction<Prompt[]>) => {
      state.prompts = action.payload;
    },
    setChunks: (state, action) => {
      state.chunks = action.payload;
    },
    setModalStateDeleteConv: (state, action: PayloadAction<ActiveState>) => {
      state.modalState = action.payload;
    },
    setTemplateAgents: (state, action) => {
      state.templateAgents = action.payload;
    },
    setAgents: (state, action) => {
      state.agents = action.payload;
    },
    setSharedAgents: (state, action) => {
      state.sharedAgents = action.payload;
    },
    setSelectedAgent: (state, action) => {
      state.selectedAgent = action.payload;
    },
    setSelectedModel: (state, action: PayloadAction<Model | null>) => {
      state.selectedModel = action.payload;
    },
    setAvailableModels: (state, action: PayloadAction<Model[]>) => {
      state.availableModels = action.payload;
    },
    setModelsLoading: (state, action: PayloadAction<boolean>) => {
      state.modelsLoading = action.payload;
    },
    setAgentFolders: (state, action: PayloadAction<AgentFolder[] | null>) => {
      state.agentFolders = action.payload;
    },
  },
});

export const {
  setApiKey,
  setSelectedDocs,
  setSourceDocs,
  setConversations,
  setToken,
  setPrompt,
  setPrompts,
  setChunks,
  setModalStateDeleteConv,
  setPaginatedDocuments,
  setTemplateAgents,
  setAgents,
  setSharedAgents,
  setSelectedAgent,
  setSelectedModel,
  setAvailableModels,
  setModelsLoading,
  setAgentFolders,
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
    const state = listenerApi.getState() as RootState;
    setLocalRecentDocs(
      state.preference.selectedDocs.length > 0
        ? state.preference.selectedDocs
        : null,
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
  matcher: isAnyOf(setSourceDocs),
  effect: (_action, listenerApi) => {
    const state = listenerApi.getState() as RootState;
    const sourceDocs = state.preference.sourceDocs;
    if (sourceDocs && sourceDocs.length > 0) {
      const validatedDocs = getLocalRecentDocs(sourceDocs);
      if (validatedDocs !== null) {
        listenerApi.dispatch(setSelectedDocs(validatedDocs));
      } else {
        listenerApi.dispatch(setSelectedDocs([]));
      }
    }
  },
});

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setPrompts),
  effect: (_action, listenerApi) => {
    const state = listenerApi.getState() as RootState;
    const availablePrompts = state.preference.prompts;
    if (availablePrompts && availablePrompts.length > 0) {
      const validatedPrompt = getLocalPrompt(availablePrompts);
      if (validatedPrompt !== null) {
        listenerApi.dispatch(setPrompt(validatedPrompt));
      } else {
        const defaultPrompt =
          availablePrompts.find((p) => p.id === 'default') ||
          availablePrompts[0];
        if (defaultPrompt) {
          listenerApi.dispatch(setPrompt(defaultPrompt));
        }
      }
    }
  },
});

prefListenerMiddleware.startListening({
  matcher: isAnyOf(setSelectedModel),
  effect: (action, listenerApi) => {
    const model = (listenerApi.getState() as RootState).preference
      .selectedModel;
    if (model) {
      localStorage.setItem('DocsGPTSelectedModel', JSON.stringify(model));
    } else {
      localStorage.removeItem('DocsGPTSelectedModel');
    }
  },
});

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
export const selectSelectedDocsStatus = (state: RootState) =>
  state.preference.selectedDocs.length > 0;
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
export const selectToken = (state: RootState) => state.preference.token;
export const selectPrompt = (state: RootState) => state.preference.prompt;
export const selectPrompts = (state: RootState) => state.preference.prompts;
export const selectChunks = (state: RootState) => state.preference.chunks;
export const selectPaginatedDocuments = (state: RootState) =>
  state.preference.paginatedDocuments;
export const selectTemplateAgents = (state: RootState) =>
  state.preference.templateAgents;
export const selectAgents = (state: RootState) => state.preference.agents;
export const selectSharedAgents = (state: RootState) =>
  state.preference.sharedAgents;
export const selectSelectedAgent = (state: RootState) =>
  state.preference.selectedAgent;
export const selectSelectedModel = (state: RootState) =>
  state.preference.selectedModel;
export const selectAvailableModels = (state: RootState) =>
  state.preference.availableModels;
export const selectModelsLoading = (state: RootState) =>
  state.preference.modelsLoading;
export const selectAgentFolders = (state: RootState) =>
  state.preference.agentFolders;
