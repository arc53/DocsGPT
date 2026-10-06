import i18next from 'i18next';

type FormatMode = 'auto' | 'date' | 'dateTime';

const DATE_ONLY_REGEX = /^(\d{4})-(\d{2})-(\d{2})$/;
const LOCAL_DATE_TIME_REGEX =
  /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/;
const HAS_TIME_REGEX = /\d{1,2}:\d{2}/;

// Dates are en-GB (DD/MM/YYYY, 24-hour) in every UI language; only relative
// phrases (formatRelative) follow the language.
const DATE_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

function parseDateValue(value: string): Date | null {
  const dateOnlyMatch = DATE_ONLY_REGEX.exec(value);
  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;
    return new Date(Number(year), Number(month) - 1, Number(day));
  }

  const localDateTimeMatch = LOCAL_DATE_TIME_REGEX.exec(value);
  if (localDateTimeMatch) {
    const [, year, month, day, hour, minute, second = '0'] = localDateTimeMatch;
    return new Date(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
    );
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDateValue(value: string, mode: FormatMode): string {
  const parsed = parseDateValue(value);
  if (!parsed) return value;

  const hasTime = HAS_TIME_REGEX.test(value);
  const shouldIncludeTime =
    mode === 'dateTime' ? hasTime : mode === 'auto' && hasTime;

  return shouldIncludeTime
    ? DATE_TIME_FORMATTER.format(parsed)
    : DATE_FORMATTER.format(parsed);
}

export function formatDate(dateString: string): string {
  return formatDateValue(dateString, 'auto');
}

export function formatDateOnly(dateString: string): string {
  return formatDateValue(dateString, 'date');
}

export function formatDateTime(dateString: string): string {
  return formatDateValue(dateString, 'dateTime');
}

/** The one placeholder for a missing value: a date, a count, an id. */
export const EMPTY_VALUE = '—';

/**
 * A timestamp as date and time, or the em dash when there is none.
 *
 * Args:
 *   value: an ISO timestamp, or nothing.
 *
 * Returns:
 *   `formatDateTime(value)`, or `EMPTY_VALUE` for an empty value.
 */
export function formatTimestamp(value?: string | null): string {
  return value ? formatDateTime(value) : EMPTY_VALUE;
}

// The app's language codes (locale/i18n.ts) that aren't BCP 47 tags.
const INTL_LOCALES: Record<string, string> = { jp: 'ja', zhTW: 'zh-TW' };

/**
 * The current UI language as a tag `Intl` understands. A value that is not a
 * valid tag (old builds stored the string "undefined") gives `en`, since every
 * `Intl` constructor throws a RangeError on it.
 */
export function intlLocale(language: string = i18next.language): string {
  if (!language) return 'en';
  try {
    return Intl.getCanonicalLocales(INTL_LOCALES[language] ?? language)[0];
  } catch {
    return 'en';
  }
}

/**
 * A deadline as the reader's own clock shows it: their browser's locale and
 * time zone, with the zone named ("Oct 20, 2026, 9:44 AM GMT+2").
 *
 * The exception to the app's en-GB dates: an expiry someone has to act before
 * (an approval link, a monitor's end) is read by people in other countries,
 * so day/month order and the zone must be theirs and visible.
 *
 * Args:
 *   value: an ISO timestamp.
 *   locale: the locale to format for; the browser's by default.
 *
 * Returns:
 *   The formatted time, or `value` unchanged when it doesn't parse.
 */
export function formatDeadline(value: string, locale?: string): string {
  const parsed = parseDateValue(value);
  if (!parsed) return value;
  return new Intl.DateTimeFormat(locale, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(parsed);
}

/**
 * A count with the UI language's digit grouping ("1,234", "1.234", "1 234").
 *
 * Args:
 *   value: the number.
 *   language: an app language code; defaults to the current one.
 *
 * Returns:
 *   The formatted number. Pass it to a plural key as its own param and keep
 *   `count` numeric, so i18next still picks the plural form.
 */
export function formatCount(
  value: number,
  language: string = i18next.language,
): string {
  return new Intl.NumberFormat(intlLocale(language)).format(value);
}

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 31_536_000_000],
  ['month', 2_592_000_000],
  ['week', 604_800_000],
  ['day', 86_400_000],
  ['hour', 3_600_000],
  ['minute', 60_000],
];

/**
 * "3 minutes ago", "yesterday", "now", "in 18 hours" in the UI language.
 *
 * Args:
 *   value: an ISO timestamp.
 *   options.now: the reference time (tests).
 *   options.locale: an app language code; defaults to the current one.
 *   options.dateAfterDays: past this many days, show the date instead.
 *   options.future: word future times as "in …"; otherwise they read "now"
 *     (a past-event field under server clock skew).
 *
 * Returns:
 *   The phrase, or null when the value is empty or unparseable.
 */
export function formatRelative(
  value: string | null | undefined,
  options: {
    now?: number;
    locale?: string;
    dateAfterDays?: number;
    future?: boolean;
  } = {},
): string | null {
  if (!value) return null;
  const then = Date.parse(value);
  if (Number.isNaN(then)) return null;
  const { now = Date.now(), locale, dateAfterDays, future = false } = options;
  // Past times read "… ago"; future ones "in …" only when the caller expects
  // them (a schedule's next run), else they clamp to "now".
  const sign = then > now ? 1 : -1;
  const diffMs = future ? Math.abs(now - then) : Math.max(0, now - then);
  if (dateAfterDays !== undefined && diffMs > dateAfterDays * 86_400_000) {
    return formatDateOnly(value);
  }
  const formatter = new Intl.RelativeTimeFormat(intlLocale(locale), {
    numeric: 'auto',
  });
  for (const [unit, ms] of RELATIVE_UNITS) {
    if (diffMs >= ms)
      return formatter.format(sign * Math.round(diffMs / ms), unit);
  }
  return formatter.format(0, 'second');
}
