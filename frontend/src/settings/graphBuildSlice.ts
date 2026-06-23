import { createSlice, PayloadAction } from '@reduxjs/toolkit';

import { sseEventReceived } from '../notifications/notificationsSlice';
import { RootState } from '../store';
import { GraphRAGSummary } from './graphragEnableUtils';

export type GraphBuildStatus = 'building' | 'completed' | 'failed';

export interface GraphBuild {
  status: GraphBuildStatus;
  current: number;
  total: number;
  nodes: number;
  edges: number;
  summary?: GraphRAGSummary;
  error?: string;
}

interface GraphBuildState {
  /** Per-source graph-extraction state, driven entirely by SSE events. */
  builds: Record<string, GraphBuild>;
}

const initialState: GraphBuildState = { builds: {} };

function toNumber(value: unknown): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export const graphBuildSlice = createSlice({
  name: 'graphBuild',
  initialState,
  reducers: {
    // Drop a source's build entry once the UI has acknowledged a terminal
    // state (e.g. after refreshing the source list), so a stale completed/
    // failed record doesn't linger.
    clearGraphBuild: (state, action: PayloadAction<string>) => {
      delete state.builds[action.payload];
    },
  },
  extraReducers: (builder) => {
    builder.addCase(sseEventReceived, (state, action) => {
      const e = action.payload;
      if (!e.type.startsWith('graph.extract.')) return;
      const scopeId =
        typeof e.scope?.id === 'string' && e.scope.id.length > 0
          ? e.scope.id
          : undefined;
      if (!scopeId) return;
      const payload = (e.payload || {}) as Record<string, unknown>;

      switch (e.type) {
        case 'graph.extract.progress': {
          const prev = state.builds[scopeId];
          // A progress event must never resurrect a terminal state (a delayed
          // or replayed frame arriving after completed/failed).
          if (prev && prev.status !== 'building') break;
          state.builds[scopeId] = {
            status: 'building',
            current: toNumber(payload.current),
            total: toNumber(payload.total),
            nodes: toNumber(payload.nodes),
            edges: toNumber(payload.edges),
          };
          break;
        }
        case 'graph.extract.completed': {
          const summary: GraphRAGSummary = {
            nodes: toNumber(payload.nodes),
            edges: toNumber(payload.edges),
            chunksProcessed: toNumber(payload.chunks_processed),
            skippedOverCap: toNumber(payload.skipped_over_cap),
            failedChunks: toNumber(payload.failed_chunks),
          };
          state.builds[scopeId] = {
            status: 'completed',
            current: toNumber(payload.chunks_processed),
            total: toNumber(payload.chunks_processed),
            nodes: summary.nodes,
            edges: summary.edges,
            summary,
          };
          break;
        }
        case 'graph.extract.failed': {
          state.builds[scopeId] = {
            status: 'failed',
            current: 0,
            total: 0,
            nodes: 0,
            edges: 0,
            error:
              typeof payload.error === 'string' ? payload.error : undefined,
          };
          break;
        }
        default:
          break;
      }
    });
  },
});

export const { clearGraphBuild } = graphBuildSlice.actions;

export const selectGraphBuilds = (state: RootState) => state.graphBuild.builds;

export default graphBuildSlice.reducer;
