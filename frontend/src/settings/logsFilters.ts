/** A Logs passthrough filter typed as `key=value`; `null` while it names no key. */
export function parsePassthroughFilter(
  input: string,
): Record<string, string> | null {
  const at = input.indexOf('=');
  if (at <= 0) return null;
  const key = input.slice(0, at).trim();
  const value = input.slice(at + 1).trim();
  if (!key || !value) return null;
  return { [key]: value };
}

/** The `key=value` text for one passthrough value (what clicking it on a row types). */
export function passthroughFilterText(key: string, value: unknown): string {
  return `${key}=${String(value)}`;
}

export type LogsDateRange = { from?: Date; to?: Date };

/**
 * The request's `date_from` / `date_to` for a day range picked in the viewer's
 * time zone: from the start of the first day to the start of the day after the
 * last one. A range with only a start day covers that one day.
 */
export function dateRangeParams(range: LogsDateRange): {
  date_from?: string;
  date_to?: string;
} {
  if (!range.from) return {};
  const start = new Date(range.from);
  start.setHours(0, 0, 0, 0);
  const end = new Date(range.to ?? range.from);
  end.setHours(0, 0, 0, 0);
  end.setDate(end.getDate() + 1);
  return { date_from: start.toISOString(), date_to: end.toISOString() };
}
