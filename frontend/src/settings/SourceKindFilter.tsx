import { useMemo, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { usePickerKindFilter } from '../hooks/usePickerKindFilter';
import { shownFilters } from '../hooks/useUrlFilter';
import type { Doc } from '../models/misc';
import {
  matchesKind,
  SOURCE_KINDS,
  type SourceKindFilter,
} from './sourceKinds';

type SourceKindToggleProps = {
  value: SourceKindFilter;
  onValueChange: (kind: SourceKindFilter) => void;
  counts: Record<SourceKindFilter, number>;
  /** `sm` on the Knowledge page's toolbar, `xs` in a picker. */
  size?: 'sm' | 'xs';
};

/**
 * The Knowledge kind filter: All · Files · Websites · Synced · Wikis ·
 * Shared, each with its count. A kind with no sources is left out (unless
 * picked), and nothing is drawn while no kind would narrow the list. The track hugs
 * its items and scrolls sideways when it outgrows its row.
 */
export function SourceKindToggle({
  value,
  onValueChange,
  counts,
  size = 'sm',
}: SourceKindToggleProps) {
  const { t } = useTranslation();
  const kinds = shownFilters(SOURCE_KINDS, value, counts);
  if (kinds.length === 0) return null;
  return (
    <ToggleGroup
      type="single"
      size={size}
      value={value}
      onValueChange={(next) => next && onValueChange(next as SourceKindFilter)}
      aria-label={t('settings.sources.kindFilterLabel')}
    >
      {kinds.map((kind) => (
        <ToggleGroupItem key={kind} value={kind} count={counts[kind]}>
          {t(`settings.sources.kinds.${kind}`)}
        </ToggleGroupItem>
      ))}
    </ToggleGroup>
  );
}

const matchesSource = (kind: SourceKindFilter, doc: Doc): boolean =>
  matchesKind(kind, doc);

/**
 * A knowledge picker's kind filter (`usePickerKindFilter` with the Knowledge
 * kinds): the xs track past `PICKER_FILTER_MIN_ITEMS` sources, opening on
 * All each time the picker opens.
 *
 * Args:
 *   docs: The picker's sources.
 *   open: Whether the picker is open.
 *
 * Returns:
 *   `kind`, the sources of that kind, and `filters`, the track to draw
 *   under the search (null while hidden).
 */
export function useSourceKindFilter(
  docs: Doc[] | null | undefined,
  open: boolean,
): { kind: SourceKindFilter; docs: Doc[]; filters: ReactNode } {
  const { t } = useTranslation();
  const list = useMemo(() => docs ?? [], [docs]);
  const { kind, items, filters } = usePickerKindFilter(list, open, {
    kinds: SOURCE_KINDS,
    matches: matchesSource,
    labelOf: (k) => t(`settings.sources.kinds.${k}`),
    ariaLabel: t('settings.sources.kindFilterLabel'),
  });
  return { kind, docs: items, filters };
}
