import { describe, expect, it } from 'vitest';

import {
  EMPTY_VALUE,
  formatCount,
  formatDate,
  formatDateOnly,
  formatDateTime,
  formatDeadline,
  formatTimestamp,
  intlLocale,
} from './dateTimeUtils';

describe('dateTimeUtils', () => {
  it('formats date-only values as DD/MM/YYYY', () => {
    expect(formatDate('2026-05-21')).toBe('21/05/2026');
    expect(formatDateOnly('2026-05-21')).toBe('21/05/2026');
  });

  it('formats local datetime strings with a 24-hour time', () => {
    expect(formatDate('2026-05-21 14:30:00')).toBe('21/05/2026, 14:30');
    expect(formatDateTime('2026-05-21T14:30:00')).toBe('21/05/2026, 14:30');
  });

  it('does not invent a midnight time for date-only values', () => {
    expect(formatDateTime('2026-05-21')).toBe('21/05/2026');
  });

  it('supports ISO timestamps with fractional seconds and offsets', () => {
    const value = '2026-06-09T00:51:20.427827+00:00';
    const expected = new Intl.DateTimeFormat('en-GB', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).format(new Date(value));

    expect(formatDate(value)).toBe(expected);
    expect(formatDateTime(value)).toBe(expected);
  });

  it('parses natural-language dates into DD/MM/YYYY', () => {
    expect(formatDate('May 21, 2026')).toBe('21/05/2026');
  });

  it('returns the original value when parsing fails', () => {
    expect(formatDate('not a date')).toBe('not a date');
    expect(formatDateTime('still not a date')).toBe('still not a date');
  });
});

describe('formatRelative', () => {
  const NOW = Date.parse('2026-09-25T12:00:00Z');
  const ago = (ms: number) => new Date(NOW - ms).toISOString();

  it('returns null for empty or unparseable values', async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    expect(formatRelative(null, { now: NOW })).toBeNull();
    expect(formatRelative('garbage', { now: NOW })).toBeNull();
  });

  it('words a future time as "in …" when asked (the next scheduled run)', async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    const ahead = (ms: number) => new Date(NOW + ms).toISOString();
    const opts = { now: NOW, locale: 'en', future: true };
    expect(formatRelative(ahead(18 * 3_600_000), opts)).toBe('in 18 hours');
    // Clock skew under a minute still reads "now".
    expect(formatRelative(ahead(20_000), opts)).toBe('now');
  });

  it('clamps a future time to "now" by default (server clock skew)', async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    const ahead = (ms: number) => new Date(NOW + ms).toISOString();
    expect(formatRelative(ahead(3 * 60_000), { now: NOW, locale: 'en' })).toBe(
      'now',
    );
  });

  it('words the gap with Intl in the given language', async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    expect(formatRelative(ago(20_000), { now: NOW, locale: 'en' })).toBe('now');
    expect(formatRelative(ago(3 * 60_000), { now: NOW, locale: 'en' })).toBe(
      '3 minutes ago',
    );
    expect(
      formatRelative(ago(26 * 3_600_000), { now: NOW, locale: 'en' }),
    ).toBe('yesterday');
    expect(formatRelative(ago(3 * 60_000), { now: NOW, locale: 'de' })).toBe(
      'vor 3 Minuten',
    );
  });

  it("maps the app's language codes to BCP 47", async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    expect(formatRelative(ago(3 * 60_000), { now: NOW, locale: 'jp' })).toBe(
      '3 分前',
    );
  });

  it('falls back to a date past dateAfterDays', async () => {
    const { formatRelative } = await import('./dateTimeUtils');
    const old = ago(45 * 86_400_000);
    expect(
      formatRelative(old, { now: NOW, locale: 'en', dateAfterDays: 30 }),
    ).toBe(formatDateOnly(old));
  });
});

describe('formatCount', () => {
  it('groups digits the way the app language does', () => {
    expect(formatCount(1234567, 'en')).toBe('1,234,567');
    expect(formatCount(1234567, 'de')).toBe('1.234.567');
    expect(formatCount(1234, 'ru')).toBe('1\u00a0234');
  });

  it('maps the app codes Intl does not know', () => {
    expect(formatCount(1234, 'jp')).toBe('1,234');
    expect(formatCount(1234, 'zhTW')).toBe('1,234');
  });

  it('leaves small numbers alone', () => {
    expect(formatCount(7, 'de')).toBe('7');
  });
});

describe('formatTimestamp', () => {
  it('formats a value as date and time', () => {
    expect(formatTimestamp('2026-09-30 14:05')).toBe(
      formatDateTime('2026-09-30 14:05'),
    );
  });

  it('shows the one missing-value placeholder for an empty value', () => {
    expect(EMPTY_VALUE).toBe('—');
    expect(formatTimestamp(null)).toBe('—');
    expect(formatTimestamp(undefined)).toBe('—');
    expect(formatTimestamp('')).toBe('—');
  });
});

describe('formatDeadline', () => {
  it("uses the reader's locale and names the time zone", () => {
    const us = formatDeadline('2026-10-20T09:44:00Z', 'en-US');
    expect(us).toMatch(/^Oct 20, 2026/);
    expect(us).toMatch(/(UTC|GMT|[A-Z]{2,5})/);
    expect(formatDeadline('2026-10-20T09:44:00Z', 'en-GB')).toMatch(
      /^20 Oct 2026/,
    );
  });

  it('leaves a value that does not parse unchanged', () => {
    expect(formatDeadline('soon')).toBe('soon');
  });
});

describe('intlLocale', () => {
  it('maps app codes to BCP 47 tags', () => {
    expect(intlLocale('ru-RU')).toBe('ru-RU');
    expect(intlLocale('jp')).toBe('ja');
    expect(intlLocale('zhTW')).toBe('zh-TW');
  });

  it('falls back to en for values Intl rejects', () => {
    // Old builds stored the string "undefined" as the language.
    expect(intlLocale('undefined')).toBe('en');
    expect(intlLocale('')).toBe('en');
    expect(intlLocale('not a tag')).toBe('en');
    expect(() => new Intl.ListFormat(intlLocale('undefined'))).not.toThrow();
    expect(formatCount(1234, 'undefined')).toBe('1,234');
  });
});
