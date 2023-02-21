import { createSlice } from '@reduxjs/toolkit';
import { Doc } from './selectDocsApi';
import store from '../store';

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
      state.sourceDocs = action.payload;
    },
  },
});

export const { setApiKey, setSelectedDocs, setSourceDocs } = prefSlice.actions;
export default prefSlice.reducer;

type RootState = ReturnType<typeof store.getState>;

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
export const selectSelectedDocsStatus = (state: RootState) =>
  !!state.preference.selectedDocs;
export const selectSourceDocs = (state: RootState) =>
  state.preference.sourceDocs;
