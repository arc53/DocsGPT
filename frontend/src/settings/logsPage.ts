import type { LogData } from './types';

const at = (log: LogData) => Date.parse(log.timestamp) || 0;

/** Rows newest first; rows at the same time keep their order. */
export const newestFirst = (logs: LogData[]): LogData[] =>
  [...logs].sort((a, b) => at(b) - at(a));

/**
 * The loaded Logs pages after a live refresh read pages 1 to `pages` again.
 *
 * When more rows came in than the refresh read, the rows between it and the
 * loaded ones are in neither, and paging (by offset) has moved past them:
 * the list starts over from the refreshed pages (`reset`), and loading more
 * goes on from there. That shows as the server saying there is more while
 * the refresh's oldest finished row isn't loaded (finished rows keep their
 * id; exactly `pages * pageSize` new rows starts over too, harmlessly).
 *
 * Otherwise each refreshed page takes its slice of `fresh`, and the last one
 * the rest: the server adds running webhook rows to page 1 after paging, so
 * `fresh` can hold more rows than the pages do. Runs that were still going
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
 *   more: The server's `has_more` for the refresh.
 *
 * Returns:
 *   The pages, and whether the list started over.
 */
export function mergeLoadedPages(
  previous: Record<number, LogData[]>,
  fresh: LogData[],
  pages: number,
  pageSize: number,
  more: boolean,
): { pages: Record<number, LogData[]>; reset: boolean } {
  const slice = (n: number) =>
    fresh.slice((n - 1) * pageSize, n < pages ? n * pageSize : undefined);
  const loaded = new Set(
    Object.values(previous)
      .flat()
      .map((log) => log.id),
  );
  const anchor = [...fresh].reverse().find((log) => !log.running);
  if (more && !(anchor && loaded.has(anchor.id))) {
    const next: Record<number, LogData[]> = {};
    for (let n = 1; n <= pages; n++) next[n] = slice(n);
    return { pages: next, reset: true };
  }
  const ids = new Set(fresh.map((log) => log.id));
  const kept: LogData[] = [];
  const next = { ...previous };
  for (let n = 1; n <= pages; n++) {
    kept.push(
      ...(previous[n] ?? []).filter((log) => !log.running && !ids.has(log.id)),
    );
    next[n] = slice(n);
  }
  next[pages] = newestFirst([...next[pages], ...kept]);
  return { pages: next, reset: false };
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
