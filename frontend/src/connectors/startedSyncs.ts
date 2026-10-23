import type { SSEEvent } from '../notifications/notificationsSlice';
import type { StartedSync } from './connectorsSlice';

/**
 * How long a started sync with no word on its first ingest (live events off,
 * or the stream resumed past the event) is still taken to be indexing.
 */
export const STARTED_SYNC_GIVE_UP_MS = 15 * 60_000;

/**
 * Where a source's first ingest stands, from the recent events: a synced
 * source is listed only once it has finished.
 *
 * @param events The recent notification events, newest first.
 * @param sourceId The source to look for.
 * @returns The newest terminal state, or null while it still runs.
 */
export function firstIngestState(
  events: SSEEvent[],
  sourceId: string,
): 'completed' | 'failed' | null {
  for (const event of events) {
    if (event.scope?.id !== sourceId) continue;
    if (event.type === 'source.ingest.completed') return 'completed';
    if (event.type === 'source.ingest.failed') return 'failed';
  }
  return null;
}

/**
 * How long ago a sync started, by this browser's clock.
 *
 * @returns Milliseconds, or NaN when `startedAt` doesn't parse.
 */
export function startedSyncAge(sync: StartedSync, now = Date.now()): number {
  return now - Date.parse(sync.startedAt);
}

/**
 * Whether a started sync is still to be shown as indexing: no terminal
 * event for it yet, and not past {@link STARTED_SYNC_GIVE_UP_MS} (a start
 * time that doesn't parse counts as past it).
 */
export function isStillIndexing(
  sync: StartedSync,
  events: SSEEvent[],
  now = Date.now(),
): boolean {
  if (firstIngestState(events, sync.id) !== null) return false;
  const age = startedSyncAge(sync, now);
  return Number.isFinite(age) && age < STARTED_SYNC_GIVE_UP_MS;
}
