import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import userService from '../api/services/userService';
import { setToken } from '../preferences/preferenceSlice';
import type { UserToolType } from '../settings/types';
import { readerIdFromToken } from '../utils/personLabel';
import { isChatPickerToolVisible } from '../utils/toolUtils';

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
  /** The newest load is still out. */
  loading: boolean;
  /**
   * The newest load; any other answer is dropped. Every composer loads into
   * this one list and a chat switch remounts the composer, so the order is
   * kept here rather than per composer.
   */
  latestRequestId: string | null;
  /**
   * The switches set while the newest load was out, by tool id; its answer
   * may predate them, so they win over it. A grantee's toggle sets only
   * `in_chat`.
   */
  toggledSinceRequest: Record<
    string,
    Partial<Pick<UserToolType, 'in_chat' | 'status'>>
  >;
  /** Whose list it is: the token's user, or the token itself without one. */
  principal: string | null;
};

const initialState: ChatToolsState = {
  tools: [],
  loaded: false,
  loading: false,
  latestRequestId: null,
  toggledSinceRequest: {},
  principal: null,
};

/** The user a token signs in as; a renewal keeps it, a sign-in as someone else doesn't. */
const principalOf = (token: string | null): string | null =>
  readerIdFromToken(token) ?? token;

export const loadChatTools = createAsyncThunk<
  UserToolType[],
  { token: string | null }
>('chatTools/load', async ({ token }) => {
  try {
    const response = await userService.getUserTools(token);
    const data = await response.json();
    return ((data.tools || []) as UserToolType[]).filter(
      isChatPickerToolVisible,
    );
  } catch (error) {
    console.error('Error fetching tools:', error);
    throw error;
  }
});

export const chatToolsSlice = createSlice({
  name: 'chatTools',
  initialState,
  reducers: {
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
      if (state.latestRequestId) {
        state.toggledSinceRequest[id] = owner
          ? { in_chat: value, status: value }
          : { ...state.toggledSinceRequest[id], in_chat: value };
      }
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadChatTools.pending, (state, action) => {
        state.latestRequestId = action.meta.requestId;
        state.toggledSinceRequest = {};
        state.loading = true;
        state.principal = principalOf(action.meta.arg.token);
      })
      .addCase(loadChatTools.fulfilled, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        // The server may have answered before a toggle reached it.
        const toggled = state.toggledSinceRequest;
        state.tools = action.payload.map((tool) =>
          toggled[tool.id] ? { ...tool, ...toggled[tool.id] } : tool,
        );
        state.latestRequestId = null;
        state.toggledSinceRequest = {};
        state.loading = false;
        state.loaded = true;
      })
      .addCase(loadChatTools.rejected, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        state.latestRequestId = null;
        state.toggledSinceRequest = {};
        state.loading = false;
        state.loaded = true;
      })
      // Another account: its list starts over, and a load still out for the
      // old token answers into nothing. The same user's token again (sign-in
      // sets it, a session renewal replaces it) keeps both.
      .addCase(setToken, (state, action) => {
        const principal = principalOf(action.payload);
        if (principal === state.principal) return;
        return { ...initialState, principal };
      });
  },
});

export const { setChatToolInChat } = chatToolsSlice.actions;

type RootLike = { chatTools?: ChatToolsState };

const NO_TOOLS: UserToolType[] = [];
export const selectChatTools = (state: RootLike) =>
  state.chatTools?.tools ?? NO_TOOLS;
export const selectChatToolsLoaded = (state: RootLike) =>
  state.chatTools?.loaded ?? false;
export const selectChatToolsLoading = (state: RootLike) =>
  state.chatTools?.loading ?? false;

export default chatToolsSlice.reducer;
