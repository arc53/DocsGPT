import { foldSeries, OTHER_SERIES_KEY } from '../settings/foldSeries';
import type { ChartPalette } from '../utils/chartUtils';
import { formatDate } from '../utils/dateTimeUtils';
import { seriesColor, usageColors } from './UsageChart';

export type UsageBucket = {
  bucket: string;
  prompt_tokens: number;
  generated_tokens: number;
  cost: number;
  cached_tokens: number | null;
  /** Prompt tokens from the rows that reported a cache breakdown. */
  cache_eligible_prompt_tokens: number;
  group_key?: string;
};

export type GroupBy = 'none' | 'model' | 'agent' | 'source';
export type Metric = 'tokens' | 'cost';

export const GROUP_OPTIONS: { value: GroupBy; label: string }[] = [
  { value: 'none', label: 'Total' },
  { value: 'model', label: 'By model' },
  { value: 'agent', label: 'By agent' },
  { value: 'source', label: 'By flow' },
];

function valueOf(row: UsageBucket, metric: Metric): number {
  return metric === 'cost'
    ? row.cost
    : row.prompt_tokens + row.generated_tokens;
}

/**
 * Shape the admin usage series for the chart.
 *
 * Ungrouped gives one dataset per token kind (or a single cost series);
 * grouped gives one dataset per group key, each aligned to the shared bucket
 * axis so a group missing a day plots 0 rather than shifting the whole series
 * left by one bar. Past five groups, the four largest stay and the rest sum
 * into one "Other" series (`foldSeries`), so no chart colour repeats.
 *
 * @param series Usage rows from the server.
 * @param groupBy How the rows are grouped.
 * @param metric Tokens or cost.
 * @param palette The resolved theme palette; read from the DOM when omitted.
 * @returns Chart.js bar data.
 */
export function buildUsageChart(
  series: UsageBucket[],
  groupBy: GroupBy,
  metric: Metric,
  palette?: ChartPalette,
) {
  const buckets = Array.from(new Set(series.map((row) => row.bucket))).sort();
  const labels = buckets.map((bucket) => formatDate(bucket));

  if (groupBy === 'none') {
    if (metric === 'cost') {
      return {
        labels,
        datasets: [
          {
            label: 'Cost',
            data: series.map((row) => row.cost),
            backgroundColor: seriesColor(0, palette),
          },
        ],
      };
    }
    const colors = usageColors(palette);
    return {
      labels,
      datasets: [
        {
          label: 'Prompt',
          data: series.map((row) => row.prompt_tokens),
          backgroundColor: colors.prompt,
        },
        {
          label: 'Generated',
          data: series.map((row) => row.generated_tokens),
          backgroundColor: colors.generated,
        },
      ],
    };
  }

  const keys = Array.from(
    new Set(series.map((row) => row.group_key ?? 'unknown')),
  );
  // Each group aligned to the shared bucket axis, then folded past five.
  const entries = foldSeries(
    keys.map((key): [string, Record<string, number>] => {
      const byBucket = new Map(
        series
          .filter((row) => (row.group_key ?? 'unknown') === key)
          .map((row) => [row.bucket, valueOf(row, metric)]),
      );
      return [
        key,
        Object.fromEntries(
          buckets.map((bucket) => [bucket, byBucket.get(bucket) ?? 0]),
        ),
      ];
    }),
  );
  return {
    labels,
    datasets: entries.map(([key, values], index) => ({
      label: key === OTHER_SERIES_KEY ? 'Other' : key,
      data: buckets.map((bucket) => values[bucket] ?? 0),
      backgroundColor: seriesColor(index, palette),
    })),
  };
}

/**
 * Prompt-cache hit rate over the calls whose provider reported a breakdown.
 *
 * Both numerator and denominator come from the server, because a bucket is a
 * whole day and mixes reporting with non-reporting calls: filtering *buckets*
 * here would still divide by the day's entire prompt volume and understate
 * the rate by however much traffic ran on a provider that reports nothing.
 *
 * Returns null when no call in the window reported one.
 */
export function cacheHitRate(series: UsageBucket[]): number | null {
  const eligible = series.reduce(
    (sum, row) => sum + (row.cache_eligible_prompt_tokens ?? 0),
    0,
  );
  if (eligible === 0) return null;
  const cached = series.reduce((sum, row) => sum + (row.cached_tokens ?? 0), 0);
  return (cached / eligible) * 100;
}
