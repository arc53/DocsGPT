import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import userService from '../../api/services/userService';
import type { Folder, FolderType } from './types';

/** One type's folders and where its load stands. */
export type FolderListState = {
  items: Folder[];
  /** A load has answered with the list at least once. */
  loaded: boolean;
  loading: boolean;
  /** The last load failed; `items` keeps what the one before it listed. */
  failed: boolean;
  /** The load started last; only its answer is applied (loads overlap). */
  latestRequestId: string | null;
  /**
   * Folders deleted this session, by id, with the parent their contents
   * moved to (null: the root), so a page showing one steps up to the parent
   * instead of reporting a missing folder.
   */
  removedParents: Record<string, string | null>;
};

export type FoldersState = Record<FolderType, FolderListState>;

const emptyList = (): FolderListState => ({
  items: [],
  loaded: false,
  loading: false,
  failed: false,
  latestRequestId: null,
  removedParents: {},
});

const initialState: FoldersState = { agent: emptyList(), source: emptyList() };

/**
 * Load the caller's folders of one type (`GET /api/folders?type=`). Every
 * screen that shows folders of that type reads this one copy, and every
 * folder change reloads it, so counts stay the server's. A failure rejects
 * (callers may `unwrap()` it) and sets `failed`, which pages show as a load
 * error rather than an empty list.
 */
export const loadFolders = createAsyncThunk<
  Folder[],
  { type: FolderType; token: string | null }
>('folders/load', async ({ type, token }) => {
  const response = await userService.getFolders(type, token);
  if (!response?.ok) throw new Error('Failed to load folders');
  const data = await response.json();
  return Array.isArray(data?.folders) ? (data.folders as Folder[]) : [];
});

const foldersSlice = createSlice({
  name: 'folders',
  initialState,
  reducers: {
    /** A folder the server deleted: drop it now, ahead of the reload. */
    folderRemoved(
      state,
      action: PayloadAction<{
        type: FolderType;
        id: string;
        parentId: string | null;
      }>,
    ) {
      const list = state[action.payload.type];
      list.items = list.items.filter((f) => f.id !== action.payload.id);
      list.removedParents[action.payload.id] = action.payload.parentId;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadFolders.pending, (state, action) => {
        const list = state[action.meta.arg.type];
        list.latestRequestId = action.meta.requestId;
        list.loading = true;
      })
      .addCase(loadFolders.fulfilled, (state, action) => {
        const list = state[action.meta.arg.type];
        if (action.meta.requestId !== list.latestRequestId) return;
        list.latestRequestId = null;
        list.loading = false;
        list.loaded = true;
        list.failed = false;
        list.items = action.payload;
      })
      .addCase(loadFolders.rejected, (state, action) => {
        const list = state[action.meta.arg.type];
        if (action.meta.requestId !== list.latestRequestId) return;
        list.latestRequestId = null;
        list.loading = false;
        list.failed = true;
      });
  },
});

type RootLike = { folders?: FoldersState };

const EMPTY = emptyList();

/** One type's folder list and its load state. */
export const selectFolderList =
  (type: FolderType) =>
  (state: RootLike): FolderListState =>
    state.folders?.[type] ?? EMPTY;

/** One type's folders (empty until loaded). */
export const selectFolders =
  (type: FolderType) =>
  (state: RootLike): Folder[] =>
    state.folders?.[type]?.items ?? EMPTY.items;

export const { folderRemoved } = foldersSlice.actions;

export default foldersSlice.reducer;
