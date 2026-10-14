import type { LogData } from './types';

const at = (log: LogData) => Date.parse(log.timestamp) || 0;

/**
 * The first Logs page after a live refresh.
 *
 * Runs that were still going drop out (their finished row is in the fresh
 * page, or will be on its next refresh); finished rows that newer ones pushed
 * off the page stay, so nothing vanishes from a list being read. Newest first.
 *
 * Args:
 *   previous: The page as shown, if loaded.
 *   fresh: Page 1 as the server returns it now.
 */
export function mergeFirstPage(
  previous: LogData[] | undefined,
  fresh: LogData[],
): LogData[] {
  if (!previous) return fresh;
  const ids = new Set(fresh.map((log) => log.id));
  const kept = previous.filter((log) => !log.running && !ids.has(log.id));
  return [...fresh, ...kept].sort((a, b) => at(b) - at(a));
}

/** Pages in order, flattened; a row on two pages (paging shifted) shows once. */
export function uniqueLogs(pages: LogData[][]): LogData[] {
  const seen = new Set<string>();
  return pages.flat().filter((log) => {
    if (seen.has(log.id)) return false;
    seen.add(log.id);
    return true;
  });
}
