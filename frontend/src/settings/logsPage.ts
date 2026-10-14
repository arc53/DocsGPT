import type { LogData } from './types';

const at = (log: LogData) => Date.parse(log.timestamp) || 0;

/**
 * The loaded Logs pages after a live refresh read pages 1 to `pages` again.
 *
 * Each refreshed page takes its slice of `fresh`, and the last one the rest:
 * the server adds running webhook rows to page 1 after paging, so `fresh`
 * can hold more rows than the pages do. Runs that were still going
 * drop out (their finished row is in `fresh`, or past it once paging moved
 * on); finished rows that newer ones pushed past the refreshed pages stay at
 * the end of the last one, so nothing vanishes from a list being read. Pages
 * after `pages` are left as they are.
 *
 * Args:
 *   previous: The loaded pages, by number.
 *   fresh: Rows 1 to `pages * pageSize` as the server returns them now.
 *   pages: How many pages were read again.
 *   pageSize: Rows per page.
 */
export function mergeLoadedPages(
  previous: Record<number, LogData[]>,
  fresh: LogData[],
  pages: number,
  pageSize: number,
): Record<number, LogData[]> {
  const ids = new Set(fresh.map((log) => log.id));
  const kept: LogData[] = [];
  const next = { ...previous };
  for (let n = 1; n <= pages; n++) {
    kept.push(
      ...(previous[n] ?? []).filter((log) => !log.running && !ids.has(log.id)),
    );
    next[n] = fresh.slice(
      (n - 1) * pageSize,
      n < pages ? n * pageSize : undefined,
    );
  }
  next[pages] = [...next[pages], ...kept].sort((a, b) => at(b) - at(a));
  return next;
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
