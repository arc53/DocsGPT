import { configureStore } from '@reduxjs/toolkit';

import agentPreviewReducer from './agents/agentPreviewSlice';
import workflowPreviewReducer from './agents/workflow/workflowPreviewSlice';
import { conversationSlice } from './conversation/conversationSlice';
import { sharedConversationSlice } from './conversation/sharedConversationSlice';
import { getStoredRecentDocs } from './preferences/preferenceApi';
import {
  Preference,
  prefListenerMiddleware,
  prefSlice,
} from './preferences/preferenceSlice';
import uploadReducer from './upload/uploadSlice';

const key = localStorage.getItem('DocsGPTApiKey');
const prompt = localStorage.getItem('DocsGPTPrompt');
const chunks = localStorage.getItem('DocsGPTChunks');
const selectedModel = localStorage.getItem('DocsGPTSelectedModel');

const preloadedState: { preference: Preference } = {
  preference: {
    apiKey: key ?? '',
    token: localStorage.getItem('authToken') ?? null,
    prompt:
      prompt !== null
        ? JSON.parse(prompt)
        : { name: 'default', id: 'default', type: 'private' },
    prompts: [
      { name: 'default', id: 'default', type: 'public' },
      { name: 'creative', id: 'creative', type: 'public' },
      { name: 'strict', id: 'strict', type: 'public' },
    ],
    chunks: JSON.parse(chunks ?? '2').toString(),
    selectedDocs: getStoredRecentDocs(),
    conversations: {
      data: null,
      loading: false,
    },
    sourceDocs: [
      {
        name: 'default',
        date: '',
        model: '1.0',
        type: 'remote',
        id: 'default',
        retriever: 'clasic',
      },
    ],
    modalState: 'INACTIVE',
    paginatedDocuments: null,
    templateAgents: null,
    agents: null,
    sharedAgents: null,
    selectedAgent: null,
    selectedModel: selectedModel ? JSON.parse(selectedModel) : null,
    availableModels: [],
    modelsLoading: false,
    agentFolders: null,
  },
};
const store = configureStore({
  preloadedState: preloadedState,
  reducer: {
    preference: prefSlice.reducer,
    conversation: conversationSlice.reducer,
    sharedConversation: sharedConversationSlice.reducer,
    upload: uploadReducer,
    agentPreview: agentPreviewReducer,
    workflowPreview: workflowPreviewReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().concat(prefListenerMiddleware.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
export default store;

// TODO : use https://redux-toolkit.js.org/tutorials/typescript#define-typed-hooks everywere instead of direct useDispatch

// TODO : streamline async state management
