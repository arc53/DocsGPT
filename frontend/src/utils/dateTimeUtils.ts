type FormatMode = 'auto' | 'date' | 'dateTime';

const DATE_ONLY_REGEX = /^(\d{4})-(\d{2})-(\d{2})$/;
const LOCAL_DATE_TIME_REGEX =
  /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/;
const HAS_TIME_REGEX = /\d{1,2}:\d{2}/;

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
