import { createSlice } from '@reduxjs/toolkit';
import store from '../store';

interface Preference {
  apiKey: string;
}

const initialState: Preference = {
  apiKey: '',
};

export const prefSlice = createSlice({
  name: 'preference',
  initialState,
  reducers: {
    setApiKey: (state, action) => {
      state.apiKey = action.payload;
    },
  },
});

export const { setApiKey } = prefSlice.actions;
export default prefSlice.reducer;

type RootState = ReturnType<typeof store.getState>;

export const selectApiKey = (state: RootState) => state.preference.apiKey;
export const selectApiKeyStatus = (state: RootState) =>
  !!state.preference.apiKey;
