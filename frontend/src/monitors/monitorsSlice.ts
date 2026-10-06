import {
  createAsyncThunk,
  createSelector,
  createSlice,
  PayloadAction,
} from '@reduxjs/toolkit';

import monitorsService from '../api/services/monitorsService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import type { Monitor, MonitorUpdatedPayload } from './types';

export type MonitorsState = {
  /** Every monitor the client knows, by id (from the list or from events). */
  byId: Record<string, Monitor>;
  /** Ids in list order (newest first). */
  order: string[];
  loaded: boolean;
  loading: boolean;
  error: string | null;
};

const initialState: MonitorsState = {
  byId: {},
  order: [],
  loaded: false,
  loading: false,
  error: null,
};

export const MONITOR_UPDATED = 'monitor.updated';

export const loadMonitors = createAsyncThunk<
  Monitor[],
  { token: string | null }
>('monitors/load', async ({ token }) => monitorsService.list(token));

export const actOnMonitor = createAsyncThunk<
  Monitor,
  { id: string; action: 'pause' | 'resume' | 'cancel'; token: string | null }
>('monitors/act', async ({ id, action, token }) =>
  monitorsService.act(id, action, token),
);

const upsert = (state: MonitorsState, monitor: Monitor) => {
  if (!state.byId[monitor.monitor_id]) state.order.unshift(monitor.monitor_id);
  state.byId[monitor.monitor_id] = monitor;
};

/** A monitor the list hasn't loaded yet, known only from its event. */
const fromEvent = (payload: MonitorUpdatedPayload): Monitor => ({
  monitor_id: payload.monitor_id,
  description: '',
  status: payload.status,
  source_type: 'webpage',
  watching: '',
  target: null,
  interval: null,
  interval_seconds: null,
  conversation_id: payload.conversation_id,
  agent_id: null,
  created_at: null,
  expires_at: null,
  next_check_at: null,
  last_checked_at: payload.last_checked_at,
  last_changed_at: null,
  last_woken_at: null,
  check_count: payload.check_count ?? 0,
  wake_count: 0,
  max_wakes: payload.wakes_left,
  wakes_left: payload.wakes_left,
  last_error: payload.last_error ?? null,
  paused_reason: payload.paused_reason ?? null,
  approval_required: false,
});

const monitorsSlice = createSlice({
  name: 'monitors',
  initialState,
  reducers: {},
  extraReducers: (builder) => {
    builder
      .addCase(loadMonitors.pending, (state) => {
        state.loading = true;
        state.error = null;
      })
      .addCase(loadMonitors.fulfilled, (state, action) => {
        state.loading = false;
        state.loaded = true;
        state.byId = {};
        state.order = [];
        for (const monitor of action.payload) {
          state.byId[monitor.monitor_id] = monitor;
          state.order.push(monitor.monitor_id);
        }
      })
      .addCase(loadMonitors.rejected, (state, action) => {
        state.loading = false;
        state.error = action.error.message ?? 'error';
      })
      .addCase(actOnMonitor.fulfilled, (state, action) => {
        upsert(state, action.payload);
      })
      .addMatcher(
        (action) => action.type === sseEventReceived.type,
        (state, action: PayloadAction<SSEEvent>) => {
          if (action.payload.type !== MONITOR_UPDATED) return;
          const payload = action.payload.payload as
            MonitorUpdatedPayload | undefined;
          if (!payload?.monitor_id) return;
          const known = state.byId[payload.monitor_id];
          if (!known) {
            upsert(state, fromEvent(payload));
            return;
          }
          known.status = payload.status;
          known.wakes_left = payload.wakes_left;
          known.last_checked_at = payload.last_checked_at;
          if (payload.check_count !== undefined)
            known.check_count = payload.check_count;
          if (payload.last_error !== undefined)
            known.last_error = payload.last_error;
          if (payload.paused_reason !== undefined)
            known.paused_reason = payload.paused_reason;
        },
      );
  },
});

export default monitorsSlice.reducer;

/** Stores built for a single component in tests may have no monitors slice. */
export type WithMonitors = { monitors?: MonitorsState };

export const selectMonitorsState = (state: WithMonitors): MonitorsState =>
  state.monitors ?? initialState;

export const selectMonitors = createSelector(
  [selectMonitorsState],
  ({ order, byId }): Monitor[] =>
    order.map((id) => byId[id]).filter((m): m is Monitor => Boolean(m)),
);

/** True while some monitor of this conversation is active (the "watching" mark). */
/** One monitor, when the store knows it. */
export const selectMonitor = (
  state: WithMonitors,
  monitorId: string,
): Monitor | undefined => selectMonitorsState(state).byId[monitorId];

export const selectIsWatching = (
  state: WithMonitors,
  conversationId: string,
): boolean => {
  const { order, byId } = selectMonitorsState(state);
  return order.some((id) => {
    const monitor = byId[id];
    return (
      monitor?.conversation_id === conversationId && monitor.status === 'active'
    );
  });
};
