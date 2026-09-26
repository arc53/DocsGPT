import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export type ActionToastVariant = 'success' | 'destructive';

export type ActionToastState = {
  id: number;
  variant: ActionToastVariant;
  message: string;
};

type SliceState = { current: ActionToastState | null; nextId: number };

const initialState: SliceState = { current: null, nextId: 1 };

/**
 * One transient result card for an action a page just ran (the admin Users
 * actions today). A new result replaces the previous one; the fresh `id`
 * restarts the card's auto-dismiss timer.
 */
const actionToastSlice = createSlice({
  name: 'actionToast',
  initialState,
  reducers: {
    showActionToast(
      state,
      action: PayloadAction<{ variant: ActionToastVariant; message: string }>,
    ) {
      state.current = { id: state.nextId, ...action.payload };
      state.nextId += 1;
    },
    dismissActionToast(state, action: PayloadAction<number>) {
      if (state.current?.id === action.payload) state.current = null;
    },
  },
});

export const { showActionToast, dismissActionToast } = actionToastSlice.actions;

export const selectActionToast = (state: {
  actionToast: SliceState;
}): ActionToastState | null => state.actionToast.current;

export default actionToastSlice.reducer;
