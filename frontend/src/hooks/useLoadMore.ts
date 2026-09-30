import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Watches a sentinel placed after a list's last item and calls `onReach`
 * when it comes near the screen. It works in whatever scrolls (the page, a
 * panel body, a capped box), so it never needs a scroller of its own.
 *
 * Args:
 *   onReach: Called when the sentinel comes into view.
 *   enabled: Off while a page is loading, after the last page or on an error.
 *   rearmKey: Change it after each load (the item count): the observer is
 *     re-created, so a sentinel that is still in view fires again and a short
 *     page is followed by the next without another scroll.
 *
 * Returns:
 *   A callback ref for the sentinel element.
 */
export function useScrollSentinel(
  onReach: () => void,
  enabled: boolean,
  rearmKey?: unknown,
): (node: Element | null) => void {
  const onReachRef = useRef(onReach);
  onReachRef.current = onReach;
  const [node, setNode] = useState<Element | null>(null);

  useEffect(() => {
    if (!node || !enabled || typeof IntersectionObserver === 'undefined') {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onReachRef.current();
      },
      { rootMargin: '0px 0px 200px 0px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [node, enabled, rearmKey]);

  return setNode;
}

/** One page of a feed and the cursor of the next; `next` is null at the end. */
export type LoadMorePage<T, C> = { items: T[]; next: C | null };

type UseLoadMoreOptions<T, C> = {
  /** Fetches the page at `cursor`; null is the first page. */
  load: (cursor: C | null) => Promise<LoadMorePage<T, C>>;
  /** The filters; a change starts over from the first page. */
  resetKey: string;
};

/**
 * A newest-first feed that loads older items as its end scrolls into view.
 * A response from before the last reset is dropped, and a failed page keeps
 * the rows already loaded.
 *
 * Returns:
 *   The loaded `items` (and `setItems` for local edits), `loading`, `error`,
 *   `done`, the `sentinelRef` to put after the last item, and `retry`.
 */
export function useLoadMore<T, C>({
  load,
  resetKey,
}: UseLoadMoreOptions<T, C>) {
  const [items, setItems] = useState<T[]>([]);
  const [next, setNext] = useState<C | null>(null);
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const generation = useRef(0);
  const busy = useRef(false);
  const loadRef = useRef(load);
  loadRef.current = load;

  const fetchPage = useCallback((cursor: C | null) => {
    const issued = generation.current;
    busy.current = true;
    setLoading(true);
    setError(false);
    loadRef
      .current(cursor)
      .then((page) => {
        if (issued !== generation.current) return;
        setItems((prev) =>
          cursor === null ? page.items : [...prev, ...page.items],
        );
        setNext(page.next);
        setDone(page.next === null);
      })
      .catch(() => {
        if (issued === generation.current) setError(true);
      })
      .finally(() => {
        if (issued !== generation.current) return;
        busy.current = false;
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    generation.current += 1;
    busy.current = false;
    setItems([]);
    setNext(null);
    setDone(false);
    fetchPage(null);
  }, [resetKey, fetchPage]);

  const loadNext = () => {
    if (busy.current || done || error || next === null) return;
    fetchPage(next);
  };

  const sentinelRef = useScrollSentinel(
    loadNext,
    !loading && !done && !error,
    items.length,
  );

  const retry = () => fetchPage(items.length ? next : null);

  return { items, setItems, loading, error, done, sentinelRef, retry };
}
