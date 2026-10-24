import type { SSEEvent } from '../notifications/notificationsSlice';
import type { StartedSync } from './connectorsSlice';

/**
 * How long a started sync with no word on its first ingest (live events off,
 * or the stream resumed past the event) is still taken to be indexing. What
 * happens past it is the caller's: the connection drawer stops showing the
 * sync, Knowledge stops waiting for it but keeps its card.
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

/** A started sync with where its first ingest stands (`firstIngestState`). */
export type PendingSync = StartedSync & {
  state: 'completed' | 'failed' | null;
};

/**
 * Sorts the syncs started this session by whether a list holds their source
 * yet. Each caller applies its own give-up and reload rules to the result.
 *
 * @param started The started syncs, in start order.
 * @param isListed Whether the caller's lists hold a source.
 * @param events The recent notification events, newest first.
 * @returns `unlisted`: the syncs no list holds, in start order, each with its
 *   state; `listedFinished`: the ids of listed sources whose (re)sync
 *   finished, which need showing no longer.
 */
export function partitionStartedSyncs(
  started: StartedSync[],
  isListed: (id: string) => boolean,
  events: SSEEvent[],
): { unlisted: PendingSync[]; listedFinished: string[] } {
  const unlisted: PendingSync[] = [];
  const listedFinished: string[] = [];
  for (const sync of started) {
    const state = firstIngestState(events, sync.id);
    if (!isListed(sync.id)) unlisted.push({ ...sync, state });
    else if (state === 'completed') listedFinished.push(sync.id);
  }
  return { unlisted, listedFinished };
}

/**
 * The ids of the syncs in one state, joined: an effect key that changes
 * only when that set does.
 */
export const syncIdsKey = (
  syncs: PendingSync[],
  state: PendingSync['state'],
): string =>
  syncs
    .filter((sync) => sync.state === state)
    .map((sync) => sync.id)
    .join(',');

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
