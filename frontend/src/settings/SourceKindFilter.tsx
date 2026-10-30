import { useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { ToggleGroup, ToggleGroupItem } from '../components/ui/toggle-group';
import { shownFilters } from '../hooks/useUrlFilter';
import type { Doc } from '../models/misc';
import {
  kindCounts,
  matchesKind,
  SOURCE_KINDS,
  type SourceKindFilter,
} from './sourceKinds';

/**
 * The kinds worth drawing: `shownFilters`, and none at all while All is
 * picked and no kind would narrow the list (every source is one kind).
 */
const shownKinds = (
  value: SourceKindFilter,
  counts: Record<SourceKindFilter, number>,
): SourceKindFilter[] => {
  const kinds = shownFilters(SOURCE_KINDS, value, counts);
  const narrows = kinds.some(
    (kind) => kind !== 'all' && counts[kind] !== counts.all,
  );
  return value === 'all' && !narrows ? [] : kinds;
};

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
  const kinds = shownKinds(value, counts);
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

/**
 * A knowledge picker's kind filter. It opens on All every time the picker
 * opens, counts the picker's whole list, and narrows it to the picked kind
 * (the picker's search narrows that further).
 *
 * Args:
 *   docs: The picker's sources.
 *   open: Whether the picker is open.
 *
 * Returns:
 *   `kind`, the sources of that kind, and `filters`, the toggle to draw
 *   under the search (null when the list has one kind).
 */
export function useSourceKindFilter(
  docs: Doc[] | null | undefined,
  open: boolean,
): { kind: SourceKindFilter; docs: Doc[]; filters: ReactNode } {
  const [kind, setKind] = useState<SourceKindFilter>('all');
  const [wasOpen, setWasOpen] = useState(open);
  if (wasOpen !== open) {
    setWasOpen(open);
    if (open) setKind('all');
  }
  const list = useMemo(() => docs ?? [], [docs]);
  const counts = useMemo(() => kindCounts(list), [list]);
  const shown = useMemo(
    () => list.filter((doc) => matchesKind(kind, doc)),
    [list, kind],
  );
  return {
    kind,
    docs: shown,
    filters:
      shownKinds(kind, counts).length > 0 ? (
        <SourceKindToggle
          size="xs"
          value={kind}
          onValueChange={setKind}
          counts={counts}
        />
      ) : null,
  };
}
