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

// The app's language codes (locale/i18n.ts) that aren't BCP 47 tags.
const INTL_LOCALES: Record<string, string> = { jp: 'ja', zhTW: 'zh-TW' };

/** The current UI language as a tag `Intl` understands. */
export function intlLocale(language: string = i18next.language): string {
  if (!language) return 'en';
  return INTL_LOCALES[language] ?? language;
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
 * "3 minutes ago", "yesterday", "now" in the UI language.
 *
 * Args:
 *   value: an ISO timestamp.
 *   options.now: the reference time (tests).
 *   options.locale: an app language code; defaults to the current one.
 *   options.dateAfterDays: past this many days, show the date instead.
 *
 * Returns:
 *   The phrase, or null when the value is empty or unparseable.
 */
export function formatRelative(
  value: string | null | undefined,
  options: { now?: number; locale?: string; dateAfterDays?: number } = {},
): string | null {
  if (!value) return null;
  const then = Date.parse(value);
  if (Number.isNaN(then)) return null;
  const { now = Date.now(), locale, dateAfterDays } = options;
  const diffMs = Math.max(0, now - then);
  if (dateAfterDays !== undefined && diffMs > dateAfterDays * 86_400_000) {
    return formatDateOnly(value);
  }
  const formatter = new Intl.RelativeTimeFormat(intlLocale(locale), {
    numeric: 'auto',
  });
  for (const [unit, ms] of RELATIVE_UNITS) {
    if (diffMs >= ms) return formatter.format(-Math.round(diffMs / ms), unit);
  }
  return formatter.format(0, 'second');
}
