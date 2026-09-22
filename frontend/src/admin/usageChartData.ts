import { formatDate } from '../utils/dateTimeUtils';
import { seriesColor, usageColors } from './UsageChart';

export type UsageBucket = {
  bucket: string;
  prompt_tokens: number;
  generated_tokens: number;
  cost: number;
  cached_tokens: number | null;
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
 * left by one bar.
 */
export function buildUsageChart(
  series: UsageBucket[],
  groupBy: GroupBy,
  metric: Metric,
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
            backgroundColor: seriesColor(0),
          },
        ],
      };
    }
    const colors = usageColors();
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
  return {
    labels,
    datasets: keys.map((key, index) => {
      const byBucket = new Map(
        series
          .filter((row) => (row.group_key ?? 'unknown') === key)
          .map((row) => [row.bucket, valueOf(row, metric)]),
      );
      return {
        label: key,
        data: buckets.map((bucket) => byBucket.get(bucket) ?? 0),
        backgroundColor: seriesColor(index),
      };
    }),
  };
}

/**
 * Prompt-cache hit rate over the rows whose provider reported a breakdown.
 *
 * NULL cached_tokens means "the provider said nothing", which is not the same
 * as "no cache hits" — counting those rows as 0 would understate the rate.
 * Returns null when nothing reported.
 */
export function cacheHitRate(series: UsageBucket[]): number | null {
  const reported = series.filter((row) => row.cached_tokens !== null);
  if (reported.length === 0) return null;
  const prompt = reported.reduce((sum, row) => sum + row.prompt_tokens, 0);
  if (prompt === 0) return null;
  const cached = reported.reduce(
    (sum, row) => sum + (row.cached_tokens ?? 0),
    0,
  );
  return (cached / prompt) * 100;
}
