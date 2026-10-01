import { useCallback, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * A list's page kept in the URL, so a reload or Back lands on the same page.
 * It replaces the history entry instead of pushing one per page.
 *
 * Args:
 *   name: The search param ("page"); page 1 leaves it out.
 *
 * Returns:
 *   `[page, setPage]`, the page 1-based.
 */
export function usePageParam(name: string): [number, (page: number) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const raw = Number(searchParams.get(name));
  const page = Number.isInteger(raw) && raw > 1 ? raw : 1;

  const setPage = useCallback(
    (next: number) =>
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (next > 1) params.set(name, String(next));
          else params.delete(name);
          return params;
        },
        { replace: true },
      ),
    [name, setSearchParams],
  );

  return [page, setPage];
}

function readSize(key: string, options: number[], fallback: number): number {
  try {
    const stored = Number(localStorage.getItem(key));
    if (options.includes(stored)) return stored;
  } catch {
    // Storage blocked (private mode): fall back to the default.
  }
  return fallback;
}

/**
 * A list's page size, remembered on this device.
 *
 * Args:
 *   storageKey: The localStorage key ("DocsGPTPageSize:sources").
 *   options: The sizes the list offers; a stored size that is no longer
 *     offered falls back to the default.
 *   defaultSize: The size before any choice; the first option if omitted.
 *
 * Returns:
 *   `[pageSize, setPageSize]`.
 */
export function usePageSize(
  storageKey: string,
  options: number[],
  defaultSize: number = options[0],
): [number, (size: number) => void] {
  const [pageSize, setPageSizeState] = useState(() =>
    readSize(storageKey, options, defaultSize),
  );

  const setPageSize = useCallback(
    (size: number) => {
      setPageSizeState(size);
      try {
        localStorage.setItem(storageKey, String(size));
      } catch {
        // Not remembered, but still applied.
      }
    },
    [storageKey],
  );

  return [pageSize, setPageSize];
}

/**
 * The page size of a usually short list (tools, models, teams): big enough
 * that a normal list never splits, and a multiple of 12 for the grids.
 */
export const SHORT_LIST_PAGE_SIZE = 48;

/**
 * Pages a list that is already loaded in full (tools, teams): the safety-net
 * pager for lists that are usually short.
 *
 * Args:
 *   items: The whole list, already searched and filtered.
 *   pageSize: Items per page.
 *   resetKey: The search and filters; a change starts on page 1.
 *
 * Returns:
 *   `page` (kept within the pages left when the list shrinks), `setPage`
 *   and the current page's `pageItems`.
 */
export function useClientPage<T>(
  items: T[],
  pageSize: number,
  resetKey: string,
): { page: number; setPage: (page: number) => void; pageItems: T[] } {
  const [page, setPage] = useState(1);
  const [lastKey, setLastKey] = useState(resetKey);
  if (lastKey !== resetKey) {
    setLastKey(resetKey);
    setPage(1);
  }
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const current = Math.min(page, pageCount);
  const start = (current - 1) * pageSize;
  return {
    page: current,
    setPage,
    pageItems: items.slice(start, start + pageSize),
  };
}
