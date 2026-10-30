import { useMemo, useState, type ReactNode } from 'react';

import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { shownFilters } from './useUrlFilter';

/**
 * A picker draws its kind track only past this many rows: about one screen
 * of two-line rows in a 600px picker. Below it the list fits without
 * scrolling, and the track would only take room.
 */
export const PICKER_FILTER_MIN_ITEMS = 10;

type PickerKindFilterOptions<T, K extends string> = {
  /** The kinds, All first (the same split as the list page's track). */
  kinds: readonly K[];
  /** Whether an item is of a kind; `all` keeps every item. */
  matches: (kind: K, item: T) => boolean;
  labelOf: (kind: K) => string;
  /** Names the track for screen readers. */
  ariaLabel: string;
};

/**
 * A picker's kind filter: the xs ToggleGroup under its search, with each
 * kind's count. It opens on All every time the picker opens and narrows the
 * picker's list to the picked kind (the search narrows it further). The
 * track shows only past `PICKER_FILTER_MIN_ITEMS` rows, and, by the
 * `shownFilters` rules, without kinds that hold nothing and not at all when
 * no kind would narrow the list.
 *
 * Args:
 *   list: The picker's items.
 *   open: Whether the picker is open.
 *   options: The kinds, the match rule, the labels and the track's name.
 *
 * Returns:
 *   `kind`, the `items` of that kind, and `filters`, the track to pass as
 *   the picker's `filters` (null while hidden).
 */
export function usePickerKindFilter<T, K extends string>(
  list: readonly T[],
  open: boolean,
  { kinds, matches, labelOf, ariaLabel }: PickerKindFilterOptions<T, K>,
): { kind: K; items: T[]; filters: ReactNode } {
  const all = kinds[0];
  const [kind, setKind] = useState<K>(all);
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) setKind(all);
  }
  const counts = useMemo(
    () =>
      Object.fromEntries(
        kinds.map((k) => [k, list.filter((item) => matches(k, item)).length]),
      ) as Record<K, number>,
    [list, kinds, matches],
  );
  const items = useMemo(
    () => list.filter((item) => matches(kind, item)),
    [list, kind, matches],
  );
  const shown = shownFilters(kinds, kind, counts);
  const visible = kind !== all || list.length > PICKER_FILTER_MIN_ITEMS;
  return {
    kind,
    items,
    filters:
      visible && shown.length > 0 ? (
        <ToggleGroup
          type="single"
          size="xs"
          value={kind}
          onValueChange={(next) => next && setKind(next as K)}
          aria-label={ariaLabel}
        >
          {shown.map((k) => (
            <ToggleGroupItem key={k} value={k} count={counts[k]}>
              {labelOf(k)}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
      ) : null,
  };
}
