import { createAsyncThunk, createSlice } from '@reduxjs/toolkit';

import connectorsService from '../api/services/connectorsService';
import type { Connection, ConnectorDefinition } from './types';

export type ConnectorsState = {
  catalog: ConnectorDefinition[];
  connections: Connection[];
  loading: boolean;
  loaded: boolean;
  failed: boolean;
};

const initialState: ConnectorsState = {
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
  reducers: {},
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

type RootLike = { connectors: ConnectorsState };

export const selectConnectorCatalog = (state: RootLike) =>
  state.connectors.catalog;
export const selectConnections = (state: RootLike) =>
  state.connectors.connections;
export const selectConnectorsLoading = (state: RootLike) =>
  state.connectors.loading;
export const selectConnectorsLoaded = (state: RootLike) =>
  state.connectors.loaded;
export const selectConnectorsFailed = (state: RootLike) =>
  state.connectors.failed;

export default connectorsSlice.reducer;
