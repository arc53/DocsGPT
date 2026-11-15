import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import userService from '../../api/services/userService';
import { captureWorkspace } from '../../workspace/requestWorkspace';
import { switchWorkspace } from '../../workspace/workspaceSlice';
import type { Folder, ItemKind } from './types';

/** The workspace's folder tree and where its load stands. */
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

/** One tree per workspace: every page reads the same folders. */
export type FoldersState = { tree: FolderListState };

const emptyList = (): FolderListState => ({
  items: [],
  loaded: false,
  loading: false,
  failed: false,
  latestRequestId: null,
  removedParents: {},
});

const initialState: FoldersState = { tree: emptyList() };

/** What a load rejects with when the app switched workspace meanwhile. */
const STALE = 'stale_workspace';

/**
 * Load the current workspace's folder tree (`GET /api/folders`, every kind).
 * Every screen that shows folders reads this one copy, and every folder
 * change reloads it, so counts stay the server's. A failure rejects (callers
 * may `unwrap()` it) and sets `failed`, which pages show as a load error
 * rather than an empty list. An answer that comes back after a switch to
 * another workspace is dropped.
 *
 * Args:
 *   token: The session token.
 *   type: Ignored; the tree holds every kind. Kept so callers that name
 *     their page's kind still compile.
 */
export const loadFolders = createAsyncThunk<
  Folder[],
  { token: string | null; type?: ItemKind },
  { rejectValue: typeof STALE }
>('folders/load', async ({ token }, { rejectWithValue }) => {
  const workspace = captureWorkspace();
  const response = await userService.getFolders(token);
  if (!response?.ok) throw new Error('Failed to load folders');
  const data = await response.json();
  if (!workspace.isCurrent()) return rejectWithValue(STALE);
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
        /** Ignored: kept so callers that name a kind still compile. */
        type?: ItemKind;
        id: string;
        parentId: string | null;
      }>,
    ) {
      const list = state.tree;
      list.items = list.items.filter((f) => f.id !== action.payload.id);
      list.removedParents[action.payload.id] = action.payload.parentId;
    },
  },
  extraReducers: (builder) => {
    builder
      // Another workspace has another tree; a load still out answers into
      // nothing (no request id matches).
      .addCase(switchWorkspace, () => ({ tree: emptyList() }))
      .addCase(loadFolders.pending, (state, action) => {
        state.tree.latestRequestId = action.meta.requestId;
        state.tree.loading = true;
      })
      .addCase(loadFolders.fulfilled, (state, action) => {
        const list = state.tree;
        if (action.meta.requestId !== list.latestRequestId) return;
        list.latestRequestId = null;
        list.loading = false;
        list.loaded = true;
        list.failed = false;
        list.items = action.payload;
      })
      .addCase(loadFolders.rejected, (state, action) => {
        const list = state.tree;
        if (action.meta.requestId !== list.latestRequestId) return;
        list.latestRequestId = null;
        list.loading = false;
        // The old workspace's answer: not a failure of this one.
        if (action.payload !== STALE) list.failed = true;
      });
  },
});

type RootLike = { folders?: FoldersState };

const EMPTY = emptyList();

/** The workspace's folder tree and its load state. */
export const selectFolderTree = (state: RootLike): FolderListState =>
  state.folders?.tree ?? EMPTY;

/**
 * The folder list and its load state. Every kind reads the same tree; the
 * kind is kept so existing callers compile.
 */
export const selectFolderList =
  (kind?: ItemKind) =>
  (state: RootLike): FolderListState => {
    void kind;
    return selectFolderTree(state);
  };

/** The folders (empty until loaded); the same list for every kind. */
export const selectFolders =
  (kind?: ItemKind) =>
  (state: RootLike): Folder[] => {
    void kind;
    return selectFolderTree(state).items;
  };

export const { folderRemoved } = foldersSlice.actions;

export default foldersSlice.reducer;
