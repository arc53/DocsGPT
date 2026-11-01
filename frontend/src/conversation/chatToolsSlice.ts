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

type PendingToggle = {
  values: Partial<Pick<UserToolType, 'in_chat' | 'status'>>;
  updates: number;
};

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
   * The switches whose status update is still out, by tool id: what each
   * last set, and how many of its updates are out. A load may have been read
   * before they reached the server, so they win over its answer until the
   * last update settles. A grantee's toggle sets only `in_chat`.
   */
  pendingToggles: Record<string, PendingToggle>;
  /** Whose list it is: the token's user, or the token itself without one. */
  principal: string | null;
};

const initialState: ChatToolsState = {
  tools: [],
  loaded: false,
  loading: false,
  latestRequestId: null,
  pendingToggles: {},
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

type ToolSwitch = { id: string; value: boolean; owner: boolean };

/** Sets a listed tool's switch and holds it over loads; false when unlisted. */
const applySwitch = (
  state: ChatToolsState,
  { id, value, owner }: ToolSwitch,
): boolean => {
  const tool = state.tools.find((t) => t.id === id);
  if (!tool) return false;
  tool.in_chat = value;
  // The owner's switch is the tool's own status; a grantee's is theirs.
  if (owner) tool.status = value;
  const toggle = (state.pendingToggles[id] ??= { values: {}, updates: 0 });
  toggle.values = owner
    ? { in_chat: value, status: value }
    : { ...toggle.values, in_chat: value };
  return true;
};

export const chatToolsSlice = createSlice({
  name: 'chatTools',
  initialState,
  reducers: {
    /**
     * Ticks or unticks a tool for the user's own chats; it holds until
     * `settleChatToolToggle` reports its status update done.
     */
    setChatToolInChat(state, action: PayloadAction<ToolSwitch>) {
      const { id } = action.payload;
      if (!applySwitch(state, action.payload)) return;
      state.pendingToggles[id].updates += 1;
    },
    /**
     * A toggle's status update has answered. A refused one hands back the
     * switch to restore; the tool is held while another update is out.
     */
    settleChatToolToggle(
      state,
      action: PayloadAction<{ id: string; rollback?: Omit<ToolSwitch, 'id'> }>,
    ) {
      const { id, rollback } = action.payload;
      const toggle = state.pendingToggles[id];
      if (!toggle) return;
      if (rollback) applySwitch(state, { id, ...rollback });
      toggle.updates -= 1;
      if (toggle.updates <= 0) delete state.pendingToggles[id];
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadChatTools.pending, (state, action) => {
        state.latestRequestId = action.meta.requestId;
        state.loading = true;
        state.principal = principalOf(action.meta.arg.token);
      })
      .addCase(loadChatTools.fulfilled, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        // The server may have answered before a toggle reached it.
        const held = state.pendingToggles;
        state.tools = action.payload.map((tool) =>
          held[tool.id] ? { ...tool, ...held[tool.id].values } : tool,
        );
        state.latestRequestId = null;
        state.loading = false;
        state.loaded = true;
      })
      .addCase(loadChatTools.rejected, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        state.latestRequestId = null;
        state.loading = false;
        state.loaded = true;
      })
      // Another account: its list and held toggles start over, and a load
      // or an update still out for the old token answers into nothing. The
      // same user's token again (sign-in sets it, a session renewal replaces
      // it) keeps both.
      .addCase(setToken, (state, action) => {
        const principal = principalOf(action.payload);
        if (principal === state.principal) return;
        return { ...initialState, principal };
      });
  },
});

export const { setChatToolInChat, settleChatToolToggle } =
  chatToolsSlice.actions;

type RootLike = { chatTools?: ChatToolsState };

const NO_TOOLS: UserToolType[] = [];
export const selectChatTools = (state: RootLike) =>
  state.chatTools?.tools ?? NO_TOOLS;
export const selectChatToolsLoaded = (state: RootLike) =>
  state.chatTools?.loaded ?? false;
export const selectChatToolsLoading = (state: RootLike) =>
  state.chatTools?.loading ?? false;

export default chatToolsSlice.reducer;
