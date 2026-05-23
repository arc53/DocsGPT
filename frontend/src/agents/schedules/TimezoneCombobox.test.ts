import { describe, expect, it } from 'vitest';

import { getTimezoneOffsetLabel, matchesTimezone } from './TimezoneCombobox';

describe('matchesTimezone', () => {
  it('matches case-insensitively by substring', () => {
    expect(matchesTimezone('Europe/Warsaw', 'war')).toBe(true);
    expect(matchesTimezone('Europe/Warsaw', 'WARSAW')).toBe(true);
  });

  it('treats path separators as spaces so "europe war" matches', () => {
    expect(matchesTimezone('Europe/Warsaw', 'europe war')).toBe(true);
  });

  it('treats underscores as spaces so "los angeles" matches "America/Los_Angeles"', () => {
    expect(matchesTimezone('America/Los_Angeles', 'los angeles')).toBe(true);
  });

  it('rejects non-matching queries', () => {
    expect(matchesTimezone('Europe/Warsaw', 'tokyo')).toBe(false);
    expect(matchesTimezone('Asia/Tokyo', 'warsaw')).toBe(false);
  });

  it('returns true for an empty query (no filter)', () => {
    expect(matchesTimezone('Anywhere', '')).toBe(true);
    expect(matchesTimezone('Anywhere', '   ')).toBe(true);
  });

  it('requires all tokens to match (AND semantics)', () => {
    expect(matchesTimezone('Europe/Warsaw', 'europe tokyo')).toBe(false);
    expect(matchesTimezone('America/New_York', 'new york')).toBe(true);
  });
});

describe('getTimezoneOffsetLabel', () => {
  it('returns a UTC+ string for Europe/Warsaw (DST-dependent, so just check prefix)', () => {
    const label = getTimezoneOffsetLabel('Europe/Warsaw');
    expect(label.startsWith('UTC+')).toBe(true);
  });

  it('renders the half-hour offset for Asia/Kolkata', () => {
    expect(getTimezoneOffsetLabel('Asia/Kolkata')).toContain('5:30');
  });

  it('returns exactly "UTC" for the UTC zone (no +0 suffix)', () => {
    expect(getTimezoneOffsetLabel('UTC')).toBe('UTC');
  });

  it('returns a UTC- string for America/Los_Angeles (always west of UTC)', () => {
    const label = getTimezoneOffsetLabel('America/Los_Angeles');
    expect(label.startsWith('UTC-')).toBe(true);
  });

  it('is stable: repeat calls return the same value (cache hit)', () => {
    const first = getTimezoneOffsetLabel('Asia/Kolkata');
    const second = getTimezoneOffsetLabel('Asia/Kolkata');
    expect(second).toBe(first);
  });

  it('degrades gracefully on an invalid timezone (returns input)', () => {
    expect(getTimezoneOffsetLabel('Not/A_Zone_xyz')).toBe('Not/A_Zone_xyz');
  });
});
