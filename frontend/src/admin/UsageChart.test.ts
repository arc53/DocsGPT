import { describe, expect, it } from 'vitest';

import { seriesColor, usageColors } from './UsageChart';

const palette = {
  primary: 'c1',
  series: ['c1', 'c2', 'c3', 'c4', 'c5'],
  success: 's',
  warning: 'w',
  destructive: 'd',
  border: 'b',
  mutedForeground: 'm',
};

describe('usageColors', () => {
  it('draws prompt in chart-1 and generated in chart-2', () => {
    expect(usageColors(palette)).toEqual({ prompt: 'c1', generated: 'c2' });
  });

  it('reads the theme tokens when no palette is passed', () => {
    expect(usageColors()).toEqual({ prompt: '#7d54d1', generated: '#2563eb' });
  });
});

describe('seriesColor', () => {
  it('walks chart-1 to chart-5 in order', () => {
    expect([0, 1, 2, 3, 4].map((i) => seriesColor(i, palette))).toEqual(
      palette.series,
    );
  });

  it('never leaves the five chart tokens', () => {
    expect(seriesColor(5, palette)).toBe('c1');
  });
});
