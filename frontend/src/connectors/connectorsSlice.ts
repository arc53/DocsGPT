import {
  createAsyncThunk,
  createSelector,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import connectorsService from '../api/services/connectorsService';
import {
  PERSONAL_WORKSPACE,
  requestWorkspace,
} from '../workspace/requestWorkspace';
import { connectionCan } from './teamConnections';
import type { Connection, ConnectorDefinition } from './types';

/**
 * A source a connection's sync just started. The server lists a synced
 * source only once its first ingest has finished, so the connection drawer
 * shows these meanwhile, as indexing.
 */
export type StartedSync = {
  id: string;
  name: string;
  connectionId: string;
  /** ISO time the sync was started. */
  startedAt: string;
  /** The Knowledge folder it was added from, which files the new source. */
  folderId?: string;
};

/**
 * One team's connections and the catalog's states for them, as any member
 * reads them (`owner=team`). Kept per team, so a switch shows the team's
 * last list at once while it reloads, and a slow answer for one team never
 * lands in another.
 */
export type TeamConnectorsEntry = {
  catalog: ConnectorDefinition[];
  connections: Connection[];
  loading: boolean;
  loaded: boolean;
  failed: boolean;
  /** The `loadTeamConnectors` call for this team started last. */
  latestRequestId: string | null;
};

export type ConnectorsState = {
  /** False when the backend predates connectors (`/api/config`). */
  enabled: boolean;
  catalog: ConnectorDefinition[];
  connections: Connection[];
  loading: boolean;
  loaded: boolean;
  failed: boolean;
  /**
   * A load has answered, listed or failed. Unlike `failed`, a reload
   * doesn't clear it, so what waits for the first answer stays put.
   */
  settled?: boolean;
  /**
   * The `loadConnectors` call started last. Loads overlap (several screens
   * refresh at once), and only its answer is applied: an older one could
   * hold connections from before a connect.
   */
  latestRequestId?: string | null;
  /** Syncs started this session, newest last (see `StartedSync`). */
  startedSyncs?: StartedSync[];
  /**
   * Each team's connections, by team id. `catalog` and `connections` above
   * stay the caller's own in every workspace: the chat's Connect card, the
   * composer and member-mode tools use the person's own accounts.
   */
  teams?: Record<string, TeamConnectorsEntry>;
};

const initialState: ConnectorsState = {
  enabled: true,
  catalog: [],
  connections: [],
  loading: false,
  loaded: false,
  failed: false,
  settled: false,
  latestRequestId: null,
  startedSyncs: [],
  teams: {},
};

const EMPTY_TEAM: TeamConnectorsEntry = Object.freeze({
  catalog: [],
  connections: [],
  loading: false,
  loaded: false,
  failed: false,
  latestRequestId: null,
}) as TeamConnectorsEntry;

/**
 * Load the catalog and the caller's connections together. Every screen that
 * shows a connector's state (the Connectors page, Add Source, Add Tool, the
 * composer pickers) reads this one copy, so a connect anywhere updates all.
 */
export const loadConnectors = createAsyncThunk<
  { catalog: ConnectorDefinition[]; connections: Connection[] },
  { token: string | null }
>('connectors/load', async ({ token }) => {
  const [catalog, connections] = await Promise.all([
    connectorsService.getCatalog(token),
    connectorsService.listConnections(token),
  ]);
  if (!catalog?.success || !connections?.success) {
    throw new Error('Failed to load connectors');
  }
  return {
    catalog: catalog.connectors ?? [],
    connections: connections.connections ?? [],
  };
});

/**
 * Load a team's connections and the catalog's states for them. The request
 * names `teamId` itself, so it goes to that team whatever the current
 * workspace is by the time it is sent.
 */
export const loadTeamConnectors = createAsyncThunk<
  { catalog: ConnectorDefinition[]; connections: Connection[] },
  { token: string | null; teamId: string }
>('connectors/loadTeam', async ({ token, teamId }) => {
  const options = { owner: 'team', workspace: teamId } as const;
  const [catalog, connections] = await Promise.all([
    connectorsService.getCatalog(token, options),
    connectorsService.listConnections(token, options),
  ]);
  if (!catalog?.success || !connections?.success) {
    throw new Error('Failed to load team connectors');
  }
  return {
    catalog: catalog.connectors ?? [],
    connections: connections.connections ?? [],
  };
});

/**
 * Load the caller's own connections again and, in a team, the team's. What
 * changes a connection (connect, reconnect, rename, remove) calls this, so
 * both lists stay current wherever it happened.
 */
export const reloadConnectors = createAsyncThunk<
  void,
  { token: string | null }
>('connectors/reload', async ({ token }, { dispatch }) => {
  const workspace = requestWorkspace();
  const loads: Promise<unknown>[] = [dispatch(loadConnectors({ token }))];
  if (workspace !== PERSONAL_WORKSPACE)
    loads.push(dispatch(loadTeamConnectors({ token, teamId: workspace })));
  await Promise.all(loads);
});

const teamEntry = (state: ConnectorsState, teamId: string) => {
  state.teams ??= {};
  state.teams[teamId] ??= { ...EMPTY_TEAM, catalog: [], connections: [] };
  return state.teams[teamId];
};

const connectorsSlice = createSlice({
  name: 'connectors',
  initialState,
  reducers: {
    setConnectorsEnabled(state, action: PayloadAction<boolean>) {
      state.enabled = action.payload;
    },
    /** Records the sources a sync started (one entry per source id). */
    syncStarted(state, action: PayloadAction<StartedSync[]>) {
      const ids = new Set(action.payload.map((sync) => sync.id));
      state.startedSyncs = [
        ...(state.startedSyncs ?? []).filter((sync) => !ids.has(sync.id)),
        ...action.payload,
      ];
    },
    /**
     * Drops started syncs that no longer need showing: their source is
     * listed, deleted, or its first ingest finished elsewhere.
     */
    syncForgotten(state, action: PayloadAction<string[]>) {
      const ids = new Set(action.payload);
      state.startedSyncs = (state.startedSyncs ?? []).filter(
        (sync) => !ids.has(sync.id),
      );
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadConnectors.pending, (state, action) => {
        state.latestRequestId = action.meta.requestId;
        state.loading = true;
        state.failed = false;
      })
      .addCase(loadConnectors.fulfilled, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        state.latestRequestId = null;
        state.loading = false;
        state.loaded = true;
        state.settled = true;
        state.catalog = action.payload.catalog;
        state.connections = action.payload.connections;
      })
      .addCase(loadConnectors.rejected, (state, action) => {
        if (action.meta.requestId !== state.latestRequestId) return;
        state.latestRequestId = null;
        state.loading = false;
        state.failed = true;
        state.settled = true;
      })
      .addCase(loadTeamConnectors.pending, (state, action) => {
        const entry = teamEntry(state, action.meta.arg.teamId);
        entry.latestRequestId = action.meta.requestId;
        entry.loading = true;
        entry.failed = false;
      })
      .addCase(loadTeamConnectors.fulfilled, (state, action) => {
        const entry = teamEntry(state, action.meta.arg.teamId);
        if (action.meta.requestId !== entry.latestRequestId) return;
        entry.latestRequestId = null;
        entry.loading = false;
        entry.loaded = true;
        entry.catalog = action.payload.catalog;
        entry.connections = action.payload.connections;
      })
      .addCase(loadTeamConnectors.rejected, (state, action) => {
        const entry = teamEntry(state, action.meta.arg.teamId);
        if (action.meta.requestId !== entry.latestRequestId) return;
        entry.latestRequestId = null;
        entry.loading = false;
        entry.failed = true;
      });
  },
});

export const { setConnectorsEnabled, syncStarted, syncForgotten } =
  connectorsSlice.actions;

type RootLike = { connectors: ConnectorsState };
/** The store's shape the workspace-aware selectors read. */
type WorkspaceRootLike = RootLike & { workspace?: { current: string } };

export const selectConnectorsEnabled = (state: RootLike) =>
  state.connectors?.enabled !== false;

export const selectConnectorCatalog = (state: RootLike) =>
  state.connectors.catalog;
export const selectConnections = (state: RootLike) =>
  state.connectors.connections;
/**
 * Whether a connection needs the user to sign in again: its sign-in expired
 * (`reconnect_needed`) or keeps failing (`error`). The one rule for every
 * surface that warns (Knowledge cards, Tools, the pickers, the nav dot, the
 * drawer), and the backend's "reconnect" card state. `disconnected` is left
 * out: the user chose it, the Connectors page shows it as a neutral state
 * with its own Reconnect, and nothing else nags about it.
 */
export const connectionNeedsSignIn = (
  connection: { status: string } | null | undefined,
) =>
  connection?.status === 'reconnect_needed' || connection?.status === 'error';

/** Any connection that needs signing in again (`connectionNeedsSignIn`). */
export const selectConnectionsNeedAttention = (state: RootLike) =>
  (state.connectors?.connections ?? []).some(connectionNeedsSignIn);
/** How many connections need signing in again (`connectionNeedsSignIn`). */
export const selectSignInNeededCount = (state: RootLike) =>
  (state.connectors?.connections ?? []).filter(connectionNeedsSignIn).length;
export const selectConnectorsLoading = (state: RootLike) =>
  state.connectors.loading;
export const selectConnectorsLoaded = (state: RootLike) =>
  state.connectors.loaded;
export const selectConnectorsFailed = (state: RootLike) =>
  state.connectors.failed;
/** A load has answered, listed or failed (see `settled`). */
export const selectConnectorsSettled = (state: RootLike) =>
  state.connectors?.settled ?? false;

const NO_STARTED_SYNCS: StartedSync[] = [];
/** The syncs started this session (see `StartedSync`). */
export const selectStartedSyncs = (state: RootLike) =>
  state.connectors?.startedSyncs ?? NO_STARTED_SYNCS;

/** A team's entry; an empty, unloaded one before its first load. */
export const selectTeamConnectors = (
  state: RootLike,
  teamId: string,
): TeamConnectorsEntry => state.connectors?.teams?.[teamId] ?? EMPTY_TEAM;
/** A team's connections (`owner=team`), as any member sees them. */
export const selectTeamConnections = (state: RootLike, teamId: string) =>
  selectTeamConnectors(state, teamId).connections;
/** The catalog with its card states worked out for a team's connections. */
export const selectTeamConnectorCatalog = (state: RootLike, teamId: string) =>
  selectTeamConnectors(state, teamId).catalog;

const currentTeam = (state: WorkspaceRootLike): string | null => {
  const current = state.workspace?.current;
  return current && current !== PERSONAL_WORKSPACE ? current : null;
};

/** The current team's entry, or null in Personal. */
export const selectCurrentTeamConnectors = (
  state: WorkspaceRootLike,
): TeamConnectorsEntry | null => {
  const team = currentTeam(state);
  return team ? selectTeamConnectors(state, team) : null;
};

/**
 * The connections the current workspace's Connectors page lists: the
 * team's in a team (never the caller's own while it loads), else the
 * caller's own.
 */
export const selectWorkspaceConnections = (state: WorkspaceRootLike) =>
  selectCurrentTeamConnectors(state)?.connections ??
  state.connectors.connections;
/** The catalog for the current workspace (see `selectWorkspaceConnections`). */
export const selectWorkspaceConnectorCatalog = (state: WorkspaceRootLike) =>
  selectCurrentTeamConnectors(state)?.catalog ?? state.connectors.catalog;
/** The current workspace's list has answered at least once with a list. */
export const selectWorkspaceConnectorsLoaded = (state: WorkspaceRootLike) =>
  selectCurrentTeamConnectors(state)?.loaded ?? state.connectors.loaded;
/** The current workspace's list is loading. */
export const selectWorkspaceConnectorsLoading = (state: WorkspaceRootLike) =>
  selectCurrentTeamConnectors(state)?.loading ?? state.connectors.loading;
/** The current workspace's last load failed. */
export const selectWorkspaceConnectorsFailed = (state: WorkspaceRootLike) =>
  selectCurrentTeamConnectors(state)?.failed ?? state.connectors.failed;

/**
 * The connections a source picker (upload modal, Drive/file pickers, the
 * setup wizard's sync step) may browse in the current workspace: in a team,
 * only the team's that the caller connected and may pick from now (never a
 * personal one: a team source reads through a team account); in Personal,
 * the caller's own.
 */
export const selectPickableConnections = createSelector(
  [selectWorkspaceConnections],
  (connections) =>
    connections.filter((connection) => connectionCan(connection, 'pick')),
);

export default connectorsSlice.reducer;
