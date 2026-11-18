import type { TFunction } from 'i18next';

import { formatClock, headingLocale } from '../utils/dateTimeUtils';
import { formatPayerDate } from './pauseReason';

/** The quota window: a UTC day, a week from Monday, or a month from the 1st. */
export type UsagePeriod = 'day' | 'week' | 'month';

/** The server's `period`, read as one of the three windows (month by default). */
export const usagePeriodOf = (value: unknown): UsagePeriod =>
  value === 'day' || value === 'week' ? value : 'month';

/**
 * The month a window ending at `resetsAt` belongs to ("November"), in the
 * reader's language: the UTC day before the reset.
 *
 * Args:
 *   resetsAt: The window's reset, ISO.
 *   language: The UI language code.
 *
 * Returns:
 *   The month's name, or an empty string when `resetsAt` does not parse.
 */
export function windowMonth(resetsAt: string, language?: string): string {
  const reset = new Date(resetsAt);
  if (Number.isNaN(reset.getTime())) return '';
  const lastDay = new Date(reset.getTime() - 24 * 60 * 60_000);
  return new Intl.DateTimeFormat(
    headingLocale(language === 'jp' ? 'ja' : language),
    { month: 'long', timeZone: 'UTC' },
  ).format(lastDay);
}

/**
 * The values the usage texts are worded from: the window's month, the reset
 * day ("1 Dec", the UTC day the window starts again) and, for a daily
 * window, the reset's time on the reader's clock.
 */
export function usagePeriodValues(
  resetsAt: string,
  language?: string,
): { month: string; date: string; time: string } {
  const reset = new Date(resetsAt);
  return {
    month: windowMonth(resetsAt, language),
    date: formatPayerDate(resetsAt, language, { utc: true }),
    time: Number.isNaN(reset.getTime()) ? '' : formatClock(reset),
  };
}

/**
 * "It resets on 1 Dec." (or "at 01:00" for a daily window).
 *
 * Args:
 *   t: The translate function.
 *   period: The window.
 *   resetsAt: The reset, ISO.
 *   language: The UI language code.
 */
export function resetSentence(
  t: TFunction,
  period: UsagePeriod,
  resetsAt: string,
  language?: string,
): string {
  const { date, time } = usagePeriodValues(resetsAt, language);
  if (period === 'day')
    return time ? t('payer.notice.resets.time', { time }) : '';
  return date ? t('payer.notice.resets.date', { date }) : '';
}
