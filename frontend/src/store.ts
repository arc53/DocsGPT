import { configureStore, createSlice, PayloadAction } from '@reduxjs/toolkit';

interface State {
  isApiKeyModalOpen: boolean;
  apiKey: string;
  isMenuOpen: boolean;
}

const initialState: State = {
  isApiKeyModalOpen: true,
  apiKey: '',
  isMenuOpen: true,
};

export const slice = createSlice({
  name: 'app',
  initialState,
  reducers: {
    toggleApiKeyModal: (state) => {
      state.isApiKeyModalOpen = !state.isApiKeyModalOpen;
      console.log('showApiKeyModal', state.isApiKeyModalOpen);
    },
    setApiKey: (state, action: PayloadAction<string>) => {
      state.apiKey = action.payload;
      console.log('setApiKey', action.payload);
    },
    toggleIsMenuOpen: (state) => {
      state.isMenuOpen = !state.isMenuOpen;
    },
  },
});

export const { toggleApiKeyModal, setApiKey, toggleIsMenuOpen } = slice.actions;

const store = configureStore({
  reducer: {
    app: slice.reducer,
  },
});

type RootState = ReturnType<typeof store.getState>;

export const selectIsApiKeyModalOpen = (state: RootState) =>
  state.app.isApiKeyModalOpen;
export const selectApiKey = (state: RootState) => state.app.apiKey;
export const selectIsMenuOpen = (state: RootState) => state.app.isMenuOpen;

export default store;
