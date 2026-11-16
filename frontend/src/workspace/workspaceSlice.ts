import {
  createAction,
  createAsyncThunk,
  createSelector,
  createSlice,
} from '@reduxjs/toolkit';

import workspacesService from '../api/services/workspacesService';
import { PERSONAL_WORKSPACE, setRequestWorkspace } from './requestWorkspace';

export type WorkspaceKind = 'personal' | 'team';

/** The caller's role in a workspace; Personal reads as `owner`. */
export type WorkspaceRole = 'owner' | 'admin' | 'editor' | 'viewer';

export type SwitchReason = 'user' | 'link' | 'lost';

/** One row of `GET /api/workspaces`. */
export type WorkspaceRow = {
  id: string;
  kind: WorkspaceKind;
  name: string;
  slug?: string | null;
  /** Team rows only. */
  role?: WorkspaceRole | null;
  member_count?: number;
  principal_label?: string | null;
  /** Team rows only: the team's owner and admins can export its chats. */
  chat_export?: boolean;
};

export type WorkspaceState = {
  /** `personal` or a team id; every list and create goes by it. */
  current: string;
  /** Personal, then the caller's teams; Personal alone until loaded. */
  workspaces: WorkspaceRow[];
  /** `/api/workspaces` has answered at least once. */
  loaded: boolean;
  loading: boolean;
  /** Counts switches, so an answer from before one is recognised as stale. */
  epoch: number;
  /** Why the last switch happened (null before any). */
  lastReason: SwitchReason | null;
  /** The load started last; only its answer is applied. */
  latestRequestId: string | null;
};

/** Where the chosen workspace is kept between visits (not synced across tabs). */
export const WORKSPACE_STORAGE_KEY = 'DocsGPTWorkspace';
const LEGACY_TEAM_KEY = 'currentTeamId';

export const PERSONAL_ROW: WorkspaceRow = {
  id: PERSONAL_WORKSPACE,
  kind: 'personal',
  name: 'Personal',
};

/**
 * The workspace chosen on the last visit. The team switcher used to keep a
 * team id under `currentTeamId` that scoped nothing; it is taken over once.
 */
function readStoredWorkspace(): string {
  try {
    const stored = localStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (stored) return stored;
    const legacy = localStorage.getItem(LEGACY_TEAM_KEY);
    if (legacy) {
      localStorage.setItem(WORKSPACE_STORAGE_KEY, legacy);
      localStorage.removeItem(LEGACY_TEAM_KEY);
      return legacy;
    }
  } catch {
    // Storage off (a private window): start in Personal.
  }
  return PERSONAL_WORKSPACE;
}

/**
 * Keeps the chosen workspace for the next visit.
 *
 * Args:
 *   id: `personal` or a team id.
 */
export function storeWorkspace(id: string): void {
  try {
    localStorage.setItem(WORKSPACE_STORAGE_KEY, id);
    localStorage.removeItem(LEGACY_TEAM_KEY);
  } catch {
    // Storage off: the choice lasts for this visit.
  }
}

const initialCurrent = readStoredWorkspace();
// Until /api/workspaces answers the stored id is used as it is; requests
// made before the first switch go there too.
setRequestWorkspace(initialCurrent, 0);

const initialState: WorkspaceState = {
  current: initialCurrent,
  workspaces: [PERSONAL_ROW],
  loaded: false,
  loading: false,
  epoch: 0,
  lastReason: null,
  latestRequestId: null,
};

/**
 * Switches the app to another workspace. Every slice holding workspace data
 * resets on it, and the main content remounts, so each page loads again.
 *
 * Args:
 *   id: `personal` or a team id.
 *   options.reason: `user` (the switcher, the default), `link` (an item or
 *     chat opened by its URL lives elsewhere) or `lost` (the caller is no
 *     longer in the team).
 */
export const switchWorkspace = createAction(
  'workspace/switched',
  (id: string, options: { reason?: SwitchReason } = {}) => ({
    payload: { id, reason: options.reason ?? 'user' },
  }),
);

/** Loads Personal and the caller's teams, with their role in each. */
export const loadWorkspaces = createAsyncThunk<
  WorkspaceRow[],
  { token: string | null }
>('workspace/load', ({ token }) => workspacesService.list({ token }));

const workspaceSlice = createSlice({
  name: 'workspace',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(switchWorkspace, (state, action) => {
        state.current = action.payload.id;
        state.epoch += 1;
        state.lastReason = action.payload.reason;
      })
      .addCase(loadWorkspaces.pending, (state, action) => {
        state.latestRequestId = action.meta.requestId;
        state.loading = true;
      })
      .addCase(loadWorkspaces.fulfilled, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        const teams = action.payload.filter((row) => row.kind === 'team');
        state.workspaces = [PERSONAL_ROW, ...teams];
        state.loaded = true;
        state.loading = false;
      })
      .addCase(loadWorkspaces.rejected, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        state.loading = false;
      });
  },
});

export default workspaceSlice.reducer;

type RootLike = { workspace: WorkspaceState };

const ROLE_RANK: Record<WorkspaceRole, number> = {
  viewer: 0,
  editor: 1,
  admin: 2,
  owner: 3,
};

/**
 * Whether a role is at least another one.
 *
 * Args:
 *   role: The caller's role, or null for none.
 *   minimum: The role needed.
 */
export function roleAtLeast(
  role: WorkspaceRole | null | undefined,
  minimum: WorkspaceRole,
): boolean {
  return !!role && ROLE_RANK[role] >= ROLE_RANK[minimum];
}

export const selectWorkspaceId = (state: RootLike): string =>
  state.workspace.current;
export const selectWorkspaces = (state: RootLike): WorkspaceRow[] =>
  state.workspace.workspaces;
export const selectWorkspacesLoaded = (state: RootLike): boolean =>
  state.workspace.loaded;
export const selectWorkspaceEpoch = (state: RootLike): number =>
  state.workspace.epoch;
export const selectIsTeamWorkspace = (state: RootLike): boolean =>
  state.workspace.current !== PERSONAL_WORKSPACE;

/**
 * The current workspace's row. A stored team the list hasn't confirmed yet
 * reads as a team with no name and no role.
 */
export const selectCurrentWorkspace = createSelector(
  [selectWorkspaceId, selectWorkspaces],
  (current, workspaces): WorkspaceRow =>
    workspaces.find((row) => row.id === current) ??
    (current === PERSONAL_WORKSPACE
      ? PERSONAL_ROW
      : { id: current, kind: 'team', name: '' }),
);

/**
 * The caller's role in the current workspace: `owner` in Personal; in a team
 * its role, read as `viewer` until the list confirms it, so nothing the role
 * may not do shows first.
 */
export const selectWorkspaceRole = (state: RootLike): WorkspaceRole => {
  const row = selectCurrentWorkspace(state);
  if (row.kind === 'personal') return 'owner';
  return row.role ?? 'viewer';
};

/** Whether New, Add, Import and New folder show: Personal, or Editor and up. */
export const selectCanCreateInWorkspace = (state: RootLike): boolean =>
  roleAtLeast(selectWorkspaceRole(state), 'editor');
