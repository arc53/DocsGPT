/** Key of the synthetic series that sums everything past the chart's colours. */
export const OTHER_SERIES_KEY = '__other__';

/** DESIGN.md: charts have five series colours, `chart-1` to `chart-5`. */
const MAX_SERIES = 5;

type SeriesEntry = [string, Record<string, number>];

const total = (series: Record<string, number>): number =>
  Object.values(series).reduce((sum, value) => sum + (value || 0), 0);

/**
 * Fit series with no meaning (models, agents, sources) into the five chart
 * colours without repeating one.
 *
 * Five or fewer series are returned unchanged. With more, the four largest
 * by total keep their original order and everything else is summed, bucket
 * by bucket, into one {@link OTHER_SERIES_KEY} series at the end, which the
 * chart draws in `chart-5`.
 *
 * @param entries Series as `[key, {bucket: value}]`, in server order.
 * @returns The series to draw, at most five.
 */
export function foldSeries(entries: SeriesEntry[]): SeriesEntry[] {
  if (entries.length <= MAX_SERIES) return entries;

  const keep = new Set(
    [...entries]
      .sort((a, b) => total(b[1]) - total(a[1]))
      .slice(0, MAX_SERIES - 1)
      .map(([key]) => key),
  );

  // Bucket order follows the first series (the chart's axis labels), then any
  // bucket only a later series reports, so Object.values lines up.
  const other: Record<string, number> = {};
  for (const [, series] of entries) {
    for (const bucket of Object.keys(series)) other[bucket] ??= 0;
  }
  for (const [key, series] of entries) {
    if (keep.has(key)) continue;
    for (const [bucket, value] of Object.entries(series)) {
      other[bucket] += value || 0;
    }
  }

  return [
    ...entries.filter(([key]) => keep.has(key)),
    [OTHER_SERIES_KEY, other],
  ];
}
