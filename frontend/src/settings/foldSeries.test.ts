import { describe, expect, it } from 'vitest';

import { foldSeries, OTHER_SERIES_KEY } from './foldSeries';

const day = (a: number, b: number) => ({ '2026-09-22': a, '2026-09-23': b });

describe('foldSeries', () => {
  it('keeps five or fewer series as they are, in order', () => {
    const entries: [string, Record<string, number>][] = [
      ['gpt-4.1', day(1, 1)],
      ['claude-sonnet-4-5', day(9, 9)],
    ];
    expect(foldSeries(entries)).toEqual(entries);
  });

  it('keeps the four largest series and sums the rest into Other', () => {
    const entries: [string, Record<string, number>][] = [
      ['a', day(1, 0)],
      ['b', day(50, 50)],
      ['c', day(2, 3)],
      ['d', day(40, 40)],
      ['e', day(30, 30)],
      ['f', day(20, 25)],
      ['g', day(4, 1)],
    ];
    const folded = foldSeries(entries);
    expect(folded.map(([key]) => key)).toEqual([
      'b',
      'd',
      'e',
      'f',
      OTHER_SERIES_KEY,
    ]);
    // a + c + g, per day.
    expect(folded[4][1]).toEqual({ '2026-09-22': 7, '2026-09-23': 4 });
  });

  it('treats a missing day in a folded series as zero', () => {
    const entries: [string, Record<string, number>][] = [
      ['a', day(10, 10)],
      ['b', day(10, 10)],
      ['c', day(10, 10)],
      ['d', day(10, 10)],
      ['e', { '2026-09-22': 1 }],
      ['f', day(2, 2)],
    ];
    expect(foldSeries(entries)[4][1]).toEqual({
      '2026-09-22': 3,
      '2026-09-23': 2,
    });
  });

  it('lists Other buckets in the first series order, which the axis uses', () => {
    const entries: [string, Record<string, number>][] = [
      ['a', { d1: 9, d2: 9, d3: 9 }],
      ['b', { d1: 9, d2: 9, d3: 9 }],
      ['c', { d1: 9, d2: 9, d3: 9 }],
      ['d', { d1: 9, d2: 9, d3: 9 }],
      ['e', { d3: 1, d1: 2 }],
      ['f', { d2: 4 }],
    ];
    expect(Object.keys(foldSeries(entries)[4][1])).toEqual(['d1', 'd2', 'd3']);
  });
});
