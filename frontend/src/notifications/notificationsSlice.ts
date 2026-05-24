import { createSelector, createSlice, PayloadAction } from '@reduxjs/toolkit';

import { RootState } from '../store';
import { loadDismissed, saveDismissed } from './dismissedPersistence';

const DISMISSED_TOOL_APPROVALS_STORAGE_KEY = 'docsgpt:dismissedToolApprovals';

/**
 * Envelope shape published by the backend SSE endpoint
 * (`application/events/publisher.py`). Mirrors the wire JSON 1:1.
 */
export interface SSEEvent<P = Record<string, unknown>> {
  id?: string;
  type: string;
  ts?: string;
  user_id?: string;
  topic?: string;
  scope?: { kind: string; id: string };
  payload?: P;
}

/**
 * Connection-health state machine the rest of the app reads via
 * ``selectPushChannelHealthy`` to gate polling-fallback behaviour.
 *
 * - ``connecting`` — initial fetch in flight, or reconnecting after drop.
 * - ``healthy`` — at least one event (data or keepalive) received and
 *   the stream has been open >2s.
 * - ``unhealthy`` — last attempt failed or has been dropped without a
 *   successful re-establish; fall back to polling.
 */
export type PushHealth = 'connecting' | 'healthy' | 'unhealthy';

interface NotificationsState {
  health: PushHealth;
  /** Most-recent server-issued id; sent back as ``Last-Event-ID`` on reconnect. */
  lastEventId: string | null;
  /** Bounded ring of recent events for the in-app notifications surface. */
  recentEvents: SSEEvent[];
  /**
   * Wallclock ms of last received data-bearing event. SSE keepalives
   * are comment lines (no ``id:``/``data:``) and do NOT update this —
   * they're filtered out at the parser level.
   */
  lastEventReceivedAt: number | null;
  /**
   * Event ids of ``tool.approval.required`` notifications the user
   * dismissed (close button or by navigating into the conversation),
   * each tagged with the wallclock ms at which it was dismissed.
   * Keyed by the SSE event id so a *new* approval for the same
   * conversation re-surfaces; the dismissal only suppresses the one
   * specific paused-tool prompt.
   *
   * Entries are evicted by TTL first (anything older than
   * ``DISMISSED_TOOL_APPROVALS_TTL_MS``), then by FIFO cap. The TTL
   * matters because a pure FIFO with a small cap can evict a *still-
   * pending* approval id before the user acts on it — re-popping the
   * toast on the next dispatch. The 24h ceiling is longer than any
   * plausible approval-pending window.
   */
  dismissedToolApprovals: Array<{ id: string; at: number }>;
}

const RECENT_EVENTS_CAP = 100;
const DISMISSED_TOOL_APPROVALS_CAP = 200;
const DISMISSED_TOOL_APPROVALS_TTL_MS = 24 * 60 * 60 * 1000;

const initialState: NotificationsState = {
  health: 'connecting',
  lastEventId: null,
  recentEvents: [],
  lastEventReceivedAt: null,
  // Hydrate from localStorage: SSE backlog replay re-delivers the
  // originating ``tool.approval.required`` envelopes on reload.
  dismissedToolApprovals: loadDismissed(
    DISMISSED_TOOL_APPROVALS_STORAGE_KEY,
    DISMISSED_TOOL_APPROVALS_TTL_MS,
  ),
};

export const notificationsSlice = createSlice({
  name: 'notifications',
  initialState,
  reducers: {
    sseEventReceived: (state, action: PayloadAction<SSEEvent>) => {
      const e = action.payload;
      // Drop immediate duplicates. Snapshot replay + live tail can
      // both deliver the same id when the live pubsub frame and the
      // replay XRANGE overlap, and consumers that walk
      // ``recentEvents`` (FileTree, ConnectorTree, MCPServerModal,
      // ToolApprovalToast) would otherwise act on the same envelope
      // twice. The route's dedup floor catches the common case; this
      // is a belt-and-suspenders for in-tab StrictMode double-mounts
      // and any envelope that slips through with the same id.
      if (e.id && state.recentEvents[0]?.id === e.id) return;
      state.recentEvents.unshift(e);
      if (state.recentEvents.length > RECENT_EVENTS_CAP) {
        state.recentEvents.length = RECENT_EVENTS_CAP;
      }
      if (e.id) state.lastEventId = e.id;
      state.lastEventReceivedAt = Date.now();
    },
    sseHealthChanged: (state, action: PayloadAction<PushHealth>) => {
      state.health = action.payload;
    },
    /**
     * Lifecycle helper used by reconnect bookkeeping — does not record
     * an event, just stamps "we heard from the server" so the polling
     * fallback stays disabled while keepalives arrive.
     */
    sseHeartbeat: (state) => {
      state.lastEventReceivedAt = Date.now();
    },
    sseLastEventIdReset: (state) => {
      // Backlog truncated — drop the cursor so the next reconnect
      // doesn't try to resume past the retained window.
      state.lastEventId = null;
    },
    /**
     * Advance the cursor without recording an event. Fired for every
     * id-bearing frame including keepalives and id-only comments,
     * so the slice cursor tracks the freshest id the wire has
     * delivered even when no envelope was dispatched. Without this,
     * ``lastEventId`` would only advance via ``sseEventReceived`` and
     * a long quiet period of keepalives would leave it stale —
     * eventually re-snapshotting the same backlog on each reconnect
     * and exhausting the per-user replay budget.
     */
    sseLastEventIdAdvanced: (state, action: PayloadAction<string>) => {
      state.lastEventId = action.payload;
    },
    clearRecentEvents: (state) => {
      state.recentEvents = [];
    },
    /**
     * Suppress a ``tool.approval.required`` notification by the SSE
     * event id. The toast surface filters dismissed ids out; a *new*
     * approval event for the same conversation has a different id
     * and re-surfaces, which is the desired UX (each pause is its
     * own decision).
     */
    dismissToolApproval: (state, action: PayloadAction<string>) => {
      const id = action.payload;
      const now = Date.now();
      // Evict expired entries first so the TTL — not the FIFO cap —
      // governs when stale ids drop, keeping still-pending approvals
      // suppressed.
      const cutoff = now - DISMISSED_TOOL_APPROVALS_TTL_MS;
      state.dismissedToolApprovals = state.dismissedToolApprovals.filter(
        (entry) => entry.at >= cutoff && entry.id !== id,
      );
      state.dismissedToolApprovals.push({ id, at: now });
      if (state.dismissedToolApprovals.length > DISMISSED_TOOL_APPROVALS_CAP) {
        state.dismissedToolApprovals = state.dismissedToolApprovals.slice(
          -DISMISSED_TOOL_APPROVALS_CAP,
        );
      }
      saveDismissed(
        DISMISSED_TOOL_APPROVALS_STORAGE_KEY,
        state.dismissedToolApprovals,
      );
    },
  },
});

export const {
  sseEventReceived,
  sseHealthChanged,
  sseHeartbeat,
  sseLastEventIdReset,
  sseLastEventIdAdvanced,
  clearRecentEvents,
  dismissToolApproval,
} = notificationsSlice.actions;

export const selectSseHealth = (state: RootState): PushHealth =>
  state.notifications.health;

export const selectPushChannelHealthy = (state: RootState): boolean =>
  state.notifications.health === 'healthy';

export const selectLastEventId = (state: RootState): string | null =>
  state.notifications.lastEventId;

export const selectLastEventReceivedAt = (state: RootState): number | null =>
  state.notifications.lastEventReceivedAt;

export const selectRecentEvents = (state: RootState): SSEEvent[] =>
  state.notifications.recentEvents;

// Memoised so ``useSelector`` consumers don't re-render on every
// unrelated ``notifications`` state change — the underlying ``{id,at}``
// array only changes when ``dismissToolApproval`` runs, but the
// projected ``.map`` would otherwise return a fresh array each call.
export const selectDismissedToolApprovals = createSelector(
  (state: RootState) => state.notifications.dismissedToolApprovals,
  (entries) => entries.map((entry) => entry.id),
);

export default notificationsSlice.reducer;
