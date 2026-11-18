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

type RootLike = { folders?: FoldersState };

const EMPTY = emptyList();

/** The workspace's folder tree and its load state. */
export const selectFolderTree = (state: RootLike): FolderListState =>
  state.folders?.tree ?? EMPTY;

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
 * Screens that mount together each ask for the tree; while a load is out,
 * another plain load is skipped (nothing is dispatched for it) and they all
 * read the answer of the one already out. A change that needs the server's
 * tree after it passes `force`: its load goes out anyway and, started last,
 * is the one applied. A workspace switch empties the tree, so the next load
 * goes out for the new workspace.
 *
 * Args:
 *   token: The session token.
 *   type: Ignored; the tree holds every kind. Kept so callers that name
 *     their page's kind still compile.
 *   force: Load even when a load is already out (after a change).
 */
export const loadFolders = createAsyncThunk<
  Folder[],
  { token: string | null; type?: ItemKind; force?: boolean },
  { rejectValue: typeof STALE; state: RootLike }
>(
  'folders/load',
  async ({ token }, { rejectWithValue }) => {
    const workspace = captureWorkspace();
    const response = await userService.getFolders(token);
    if (!response?.ok) throw new Error('Failed to load folders');
    const data = await response.json();
    if (!workspace.isCurrent()) return rejectWithValue(STALE);
    return Array.isArray(data?.folders) ? (data.folders as Folder[]) : [];
  },
  {
    condition: ({ force }, { getState }) =>
      Boolean(force) || !selectFolderTree(getState()).loading,
  },
);

const foldersSlice = createSlice({
  name: 'folders',
  initialState,
  reducers: {
    /**
     * A folder the server created, renamed or moved, as it answered: put it
     * in now, keeping the counts the list had (the answer may lack them), so
     * the change shows even when the reload after it fails.
     */
    folderSaved(state, action: PayloadAction<Folder>) {
      const list = state.tree;
      const index = list.items.findIndex((f) => f.id === action.payload.id);
      if (index === -1) list.items.push(action.payload);
      else list.items[index] = { ...list.items[index], ...action.payload };
    },
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

export const { folderRemoved, folderSaved } = foldersSlice.actions;

export default foldersSlice.reducer;
