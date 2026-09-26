import { describe, expect, it } from 'vitest';

import { formatDate, formatDateOnly, formatDateTime } from './dateTimeUtils';

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
