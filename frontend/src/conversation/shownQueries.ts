import type { Query } from './conversationModels';

/**
 * Index of the last turn the chat shows: a compression summary an earlier
 * version stored is kept in the list but not shown, so it is never the latest
 * turn. -1 for an empty list.
 */
export function lastShownIndex(queries: Query[]): number {
  for (let index = queries.length - 1; index >= 0; index -= 1) {
    if (!queries[index].compressionSummary) return index;
  }
  return queries.length - 1;
}
