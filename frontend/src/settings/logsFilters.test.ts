import { describe, expect, it } from 'vitest';

import {
  dateRangeParams,
  parsePassthroughFilter,
  passthroughFilterText,
} from './logsFilters';

describe('parsePassthroughFilter', () => {
  it('reads key=value', () => {
    expect(parsePassthroughFilter(' user_id = emp-42 ')).toEqual({
      user_id: 'emp-42',
    });
  });

  it('keeps an = inside the value', () => {
    expect(parsePassthroughFilter('q=a=b')).toEqual({ q: 'a=b' });
  });

  it.each(['', 'emp-42', '=emp-42', 'user_id=', 'user_id=  '])(
    'is null for %j',
    (input) => {
      expect(parsePassthroughFilter(input)).toBeNull();
    },
  );

  it('round-trips a clicked value', () => {
    expect(parsePassthroughFilter(passthroughFilterText('tier', 2))).toEqual({
      tier: '2',
    });
  });
});

describe('dateRangeParams', () => {
  it('is empty without a start day', () => {
    expect(dateRangeParams({})).toEqual({});
  });

  it('covers whole local days, the last one included', () => {
    const { date_from, date_to } = dateRangeParams({
      from: new Date(2026, 9, 1, 15, 30),
      to: new Date(2026, 9, 3, 9, 0),
    });
    expect(new Date(date_from!)).toEqual(new Date(2026, 9, 1));
    expect(new Date(date_to!)).toEqual(new Date(2026, 9, 4));
  });

  it('covers one day when only the start is picked', () => {
    const { date_from, date_to } = dateRangeParams({
      from: new Date(2026, 9, 1, 12),
    });
    expect(new Date(date_from!)).toEqual(new Date(2026, 9, 1));
    expect(new Date(date_to!)).toEqual(new Date(2026, 9, 2));
  });
});
