import { configureStore } from '@reduxjs/toolkit';
import { conversationSlice } from './conversation/conversationSlice';
import { sharedConversationSlice } from './conversation/sharedConversationSlice';
import {
  Preference,
  prefListenerMiddleware,
  prefSlice,
} from './preferences/preferenceSlice';

const key = localStorage.getItem('DocsGPTApiKey');
const prompt = localStorage.getItem('DocsGPTPrompt');
const chunks = localStorage.getItem('DocsGPTChunks');
const token_limit = localStorage.getItem('DocsGPTTokenLimit');
const doc = localStorage.getItem('DocsGPTRecentDocs');

const preloadedState: { preference: Preference } = {
  preference: {
    apiKey: key ?? '',
    prompt:
      prompt !== null
        ? JSON.parse(prompt)
        : { name: 'default', id: 'default', type: 'private' },
    chunks: JSON.parse(chunks ?? '2').toString(),
    token_limit: token_limit ? parseInt(token_limit) : 2000,
    selectedDocs: doc !== null ? JSON.parse(doc) : null,
    conversations: null,
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
  },
};
const store = configureStore({
  preloadedState: preloadedState,
  reducer: {
    preference: prefSlice.reducer,
    conversation: conversationSlice.reducer,
    sharedConversation: sharedConversationSlice.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().concat(prefListenerMiddleware.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
export default store;

// TODO : use https://redux-toolkit.js.org/tutorials/typescript#define-typed-hooks everywere instead of direct useDispatch

// TODO : streamline async state management
