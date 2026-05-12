import type { AppDispatch } from '../store';
import {
  sseEventReceived,
  sseLastEventIdReset,
  type SSEEvent,
} from '../notifications/notificationsSlice';

/**
 * Single fan-out point for inbound SSE envelopes. Always dispatches
 * ``sseEventReceived`` so any slice can ``extraReducers``-listen
 * (uploadSlice does this in Phase 1D), then handles the small set of
 * envelope-types that need centralised side effects (e.g.
 * ``backlog.truncated``).
 */
export function dispatchSSEEvent(
  envelope: SSEEvent,
  dispatch: AppDispatch,
): void {
  switch (envelope.type) {
    case 'backlog.truncated':
      // Backlog window slid past the client's Last-Event-ID. Drop the
      // cursor so the next reconnect doesn't try to resume past the
      // retained window. Slices that care about full-state freshness
      // can subscribe to ``sseEventReceived`` and refetch.
      dispatch(sseLastEventIdReset());
      break;
    default:
      // No central side effect; rely on slice-level extraReducers.
      break;
  }

  dispatch(sseEventReceived(envelope));
}
