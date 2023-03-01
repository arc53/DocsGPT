import { configureStore } from '@reduxjs/toolkit';
import { conversationSlice } from './conversation/conversationSlice';
import {
  prefListenerMiddleware,
  prefSlice,
} from './preferences/preferenceSlice';

const key = localStorage.getItem('DocsGPTApiKey');
const doc = localStorage.getItem('DocsGPTRecentDocs');

const store = configureStore({
  preloadedState: {
    preference: {
      apiKey: key ?? '',
      selectedDocs: doc !== null ? JSON.parse(doc) : null,
      sourceDocs: [
        {
          language: '',
          name: 'default',
          version: '',
          dat: '',
          description: '',
          docLink: '',
          fullName: '',
          model: '1.0',
        },
      ],
    },
  },
  reducer: {
    preference: prefSlice.reducer,
    conversation: conversationSlice.reducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware().concat(prefListenerMiddleware.middleware),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;
export default store;

// TODO : use https://redux-toolkit.js.org/tutorials/typescript#define-typed-hooks everywere instead of direct useDispatch

// TODO : streamline async state management
