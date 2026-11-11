import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

type UrlFilterOptions = {
  /** The search param; `filter` by default. */
  name?: string;
  /**
   * Params dropped when the filter changes, such as a `page` from
   * `usePageParam`, so a new filter starts on page 1.
   */
  clears?: readonly string[];
};

/**
 * A list page's filter kept in the address (`?filter=connected`), so Back and
 * a reload keep it. The first value (`all`) is the default and is left out of
 * the address; an unknown value reads as the default. It replaces the history
 * entry rather than pushing one per click, and keeps the other params.
 *
 * Args:
 *   values: The filter's values, the default first (`['all', ...]`).
 *   options: `name` of the param, and `clears`, the params a change drops.
 *
 * Returns:
 *   `[filter, setFilter]`.
 */
export function useUrlFilter<T extends string>(
  values: readonly T[],
  { name = 'filter', clears = [] }: UrlFilterOptions = {},
): [T, (value: T) => void] {
  const [searchParams, setSearchParams] = useSearchParams();
  const fallback = values[0];
  const raw = searchParams.get(name) as T | null;
  const filter = raw && values.includes(raw) ? raw : fallback;
  const clearsKey = clears.join('\n');

  const setFilter = useCallback(
    (value: T) =>
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev);
          if (params.get(name) !== (value === fallback ? null : value)) {
            for (const key of clearsKey ? clearsKey.split('\n') : []) {
              params.delete(key);
            }
          }
          if (value === fallback) params.delete(name);
          else params.set(name, value);
          return params;
        },
        { replace: true },
      ),
    [name, fallback, clearsKey, setSearchParams],
  );

  return [filter, setFilter];
}

/**
 * The filter items worth showing: an item whose count is 0 is hidden unless
 * it is the selected one, and the first (All) always stays. While All is
 * picked, the group is hidden when only All would remain or when no item
 * would narrow the list (every item holds what All holds), so a filter
 * never offers a choice that changes nothing.
 *
 * Args:
 *   values: The filter's values, All first.
 *   selected: The current value.
 *   counts: Items per value.
 *
 * Returns:
 *   The values to draw, in order; empty when the group should be hidden.
 */
export function shownFilters<T extends string>(
  values: readonly T[],
  selected: T,
  counts: Record<T, number>,
): T[] {
  const all = values[0];
  const shown = values.filter(
    (value) => value === all || value === selected || counts[value] > 0,
  );
  const narrows = shown.some(
    (value) => value !== all && counts[value] !== counts[all],
  );
  return shown.length > 1 && (selected !== all || narrows) ? shown : [];
}
