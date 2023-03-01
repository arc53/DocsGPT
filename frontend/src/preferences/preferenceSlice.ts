import {
  createListenerMiddleware,
  createSlice,
  isAnyOf,
} from '@reduxjs/toolkit';
import { Doc, setLocalApiKey, setLocalRecentDocs } from './preferenceApi';
import { RootState } from '../store';

interface Preference {
  apiKey: string;
  selectedDocs: Doc | null;
  sourceDocs: Doc[] | null;
}

const initialState: Preference = {
  apiKey: '',
  selectedDocs: null,
  sourceDocs: null,
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
      state.sourceDocs?.push(...action.payload);
    },
  },
});

export const { setApiKey, setSelectedDocs, setSourceDocs } = prefSlice.actions;
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

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
export const selectSelectedDocsStatus = (state: RootState) =>
  !!state.preference.selectedDocs;
export const selectSourceDocs = (state: RootState) =>
  state.preference.sourceDocs;
export const selectSelectedDocs = (state: RootState) =>
  state.preference.selectedDocs;
