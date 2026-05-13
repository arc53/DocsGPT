import type { AppDispatch } from '../store';
import {
  sseEventReceived,
  sseLastEventIdReset,
  type SSEEvent,
} from '../notifications/notificationsSlice';

// Envelope types this build knows about. Hitting an unknown type means
// the backend published something the frontend hasn't been taught yet
// — worth a single debug line so it's visible in devtools without
// drowning the console in known per-progress traffic.
const KNOWN_TYPES: ReadonlySet<string> = new Set([
  'backlog.truncated',
  'source.ingest.queued',
  'source.ingest.progress',
  'source.ingest.completed',
  'source.ingest.failed',
  'attachment.queued',
  'attachment.progress',
  'attachment.completed',
  'attachment.failed',
  'mcp.oauth.awaiting_redirect',
  'mcp.oauth.in_progress',
  'mcp.oauth.completed',
  'mcp.oauth.failed',
  'tool.approval.required',
]);

/**
 * Single fan-out point for inbound SSE envelopes. Always dispatches
 * ``sseEventReceived`` so any slice can ``extraReducers``-listen
 * (uploadSlice does this for source-ingest events), then handles the
 * small set of envelope-types that need centralised side effects (e.g.
 * ``backlog.truncated``).
 */
export function dispatchSSEEvent(
  envelope: SSEEvent,
  dispatch: AppDispatch,
): void {
  if (!KNOWN_TYPES.has(envelope.type)) {
    console.debug('[dispatchSSEEvent] unknown envelope type', envelope.type);
  }

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
