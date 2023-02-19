import { createSlice } from '@reduxjs/toolkit';
import { Doc } from '../models/misc';
import store from '../store';

interface Preference {
  apiKey: string;
  selectedDocs: Doc | null;
}

const initialState: Preference = {
  apiKey: '',
  selectedDocs: null,
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
  },
});

export const { setApiKey, setSelectedDocs } = prefSlice.actions;
export default prefSlice.reducer;

type RootState = ReturnType<typeof store.getState>;

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
export const selectSelectedDocs = (state: RootState) =>
  state.preference.selectedDocs;
export const selectSelectedDocsStatus = (state: RootState) =>
  !!state.preference.selectedDocs;
