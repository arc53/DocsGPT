import { shownFilters } from '../hooks/useUrlFilter';
import { formatCount } from '../utils/dateTimeUtils';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from './ui/select';

type FilterSelectProps<T extends string> = {
  value: T;
  onValueChange: (value: T) => void;
  /** The filter's values, the default ("Any use") first. */
  values: readonly T[];
  counts: Record<T, number>;
  /** Each value's label: "Any use", "In use", "Unused". */
  labelOf: (value: T) => string;
  /** Names the filter for screen readers ("Filter by use"). */
  ariaLabel: string;
};

/**
 * A list page's second filter, beside its kind ToggleGroup: how the items are
 * used (Any use · In use · Unused) or their state (Any status · Connected ·
 * Needs sign-in · Not connected), as a pill Select. Each option shows its
 * count; the trigger shows the default without one, so "Any use" never
 * echoes the track's "All 102". The `shownFilters` rules apply: an option
 * with no items is left out unless picked, and with only the default left
 * nothing is drawn.
 */
export default function FilterSelect<T extends string>({
  value,
  onValueChange,
  values,
  counts,
  labelOf,
  ariaLabel,
}: FilterSelectProps<T>) {
  const shown = shownFilters(values, value, counts);
  if (shown.length === 0) return null;
  const isDefault = value === values[0];
  return (
    <Select value={value} onValueChange={(next) => onValueChange(next as T)}>
      <SelectTrigger
        className="min-w-[125px]"
        size="field"
        shape="pill"
        aria-label={ariaLabel}
      >
        <SelectValue>
          {labelOf(value)}
          {!isDefault ? (
            <span className="text-muted-foreground tabular-nums">
              {formatCount(counts[value])}
            </span>
          ) : null}
        </SelectValue>
      </SelectTrigger>
      <SelectContent fit>
        {shown.map((option) => (
          <SelectItem key={option} value={option}>
            {labelOf(option)}
            <span className="text-muted-foreground tabular-nums">
              {formatCount(counts[option])}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
