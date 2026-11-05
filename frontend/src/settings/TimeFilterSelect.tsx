import { useTranslation } from 'react-i18next';

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';

/** The analytics windows (`filter_option`), shortest first, and their labels. */
const TIME_FILTERS = [
  ['last_hour', 'hour'],
  ['last_24_hour', 'last24Hours'],
  ['last_7_days', 'last7Days'],
  ['last_15_days', 'last15Days'],
  ['last_30_days', 'last30Days'],
] as const;

export type TimeFilter = (typeof TIME_FILTERS)[number][0];

export const DEFAULT_TIME_FILTER: TimeFilter = 'last_30_days';

export type TimeFilterKey = (typeof TIME_FILTERS)[number][1];

/** A window's key (`last30Days`), for copy that names it; an unknown one reads as the default. */
export function timeFilterKey(option: string): TimeFilterKey {
  const known =
    TIME_FILTERS.find(([value]) => value === option) ??
    TIME_FILTERS.find(([value]) => value === DEFAULT_TIME_FILTER)!;
  return known[1];
}

/** The window select of Analytics and an agent's Insights. */
export default function TimeFilterSelect({
  value,
  onChange,
}: {
  value: TimeFilter;
  onChange: (value: TimeFilter) => void;
}) {
  const { t } = useTranslation();
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        const known = TIME_FILTERS.find(([option]) => option === next);
        if (known) onChange(known[0]);
      }}
    >
      <SelectTrigger
        className="min-w-[125px]"
        size="field"
        shape="pill"
        aria-label={t('activity.history.periodFilter')}
      >
        <SelectValue placeholder={t('settings.analytics.filterPlaceholder')} />
      </SelectTrigger>
      <SelectContent fit>
        {TIME_FILTERS.map(([option, key]) => (
          <SelectItem key={option} value={option}>
            {t(`settings.analytics.filterOptions.${key}`)}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
