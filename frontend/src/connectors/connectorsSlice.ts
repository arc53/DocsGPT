import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import connectorsService from '../api/services/connectorsService';
import type { Connection, ConnectorDefinition } from './types';

export type ConnectorsState = {
  /** False when the backend predates connectors (`/api/config`). */
  enabled: boolean;
  catalog: ConnectorDefinition[];
  connections: Connection[];
  loading: boolean;
  loaded: boolean;
  failed: boolean;
};

const initialState: ConnectorsState = {
  enabled: true,
  catalog: [],
  connections: [],
  loading: false,
  loaded: false,
  failed: false,
};

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

const connectorsSlice = createSlice({
  name: 'connectors',
  initialState,
  reducers: {
    setConnectorsEnabled(state, action: PayloadAction<boolean>) {
      state.enabled = action.payload;
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadConnectors.pending, (state) => {
        state.loading = true;
        state.failed = false;
      })
      .addCase(loadConnectors.fulfilled, (state, action) => {
        state.loading = false;
        state.loaded = true;
        state.catalog = action.payload.catalog;
        state.connections = action.payload.connections;
      })
      .addCase(loadConnectors.rejected, (state) => {
        state.loading = false;
        state.failed = true;
      });
  },
});

export const { setConnectorsEnabled } = connectorsSlice.actions;

type RootLike = { connectors: ConnectorsState };

export const selectConnectorsEnabled = (state: RootLike) =>
  state.connectors?.enabled !== false;

export const selectConnectorCatalog = (state: RootLike) =>
  state.connectors.catalog;
export const selectConnections = (state: RootLike) =>
  state.connectors.connections;
/** A connection that needs the user (signing in again, or failing). */
export const selectConnectionsNeedAttention = (state: RootLike) =>
  (state.connectors?.connections ?? []).some(
    (connection) =>
      connection.status === 'reconnect_needed' || connection.status === 'error',
  );
export const selectConnectorsLoading = (state: RootLike) =>
  state.connectors.loading;
export const selectConnectorsLoaded = (state: RootLike) =>
  state.connectors.loaded;
export const selectConnectorsFailed = (state: RootLike) =>
  state.connectors.failed;

export default connectorsSlice.reducer;
