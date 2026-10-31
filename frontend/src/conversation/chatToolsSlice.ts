import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

import type { UserToolType } from '../settings/types';

/**
 * The tools the composer's Tools picker lists, with whether each is on in
 * the user's own chats. The composer loads and toggles them; the empty
 * chat's suggestions read them, so a service it suggests asking about has
 * its tool on.
 */
export type ChatToolsState = {
  tools: UserToolType[];
  /** A load has answered, or failed (the list then stays as it was). */
  loaded: boolean;
};

const initialState: ChatToolsState = { tools: [], loaded: false };

export const chatToolsSlice = createSlice({
  name: 'chatTools',
  initialState,
  reducers: {
    setChatTools(state, action: PayloadAction<UserToolType[]>) {
      state.tools = action.payload;
      state.loaded = true;
    },
    chatToolsLoadFailed(state) {
      state.loaded = true;
    },
    /** Ticks or unticks a tool for the user's own chats. */
    setChatToolInChat(
      state,
      action: PayloadAction<{ id: string; value: boolean; owner: boolean }>,
    ) {
      const { id, value, owner } = action.payload;
      const tool = state.tools.find((t) => t.id === id);
      if (!tool) return;
      tool.in_chat = value;
      // The owner's switch is the tool's own status; a grantee's is theirs.
      if (owner) tool.status = value;
    },
  },
});

export const { setChatTools, chatToolsLoadFailed, setChatToolInChat } =
  chatToolsSlice.actions;

type RootLike = { chatTools?: ChatToolsState };

const NO_TOOLS: UserToolType[] = [];
export const selectChatTools = (state: RootLike) =>
  state.chatTools?.tools ?? NO_TOOLS;
export const selectChatToolsLoaded = (state: RootLike) =>
  state.chatTools?.loaded ?? false;

export default chatToolsSlice.reducer;
