// import { configureStore, createSlice } from '@reduxjs/toolkit';

import { configureStore } from '@reduxjs/toolkit';
import { prefSlice } from './preferences/preferenceSlice';

const store = configureStore({
  reducer: {
    preference: prefSlice.reducer,
  },
});

export default store;
