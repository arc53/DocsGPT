import { afterEach, describe, expect, it, vi } from 'vitest';

import { hoverColor, readChartPalette, readCssVar } from './chartUtils';

const TOKENS = [
  '--chart-1',
  '--chart-2',
  '--chart-3',
  '--chart-4',
  '--chart-5',
  '--border',
  '--muted-foreground',
  '--primary',
];

afterEach(() => {
  TOKENS.forEach((name) => document.body.style.removeProperty(name));
  vi.unstubAllGlobals();
});

describe('readCssVar', () => {
  it('reads the token from body, where the .dark class lives', () => {
    document.body.style.setProperty('--primary', '#976af3');
    expect(readCssVar('--primary', '#7d54d1')).toBe('#976af3');
  });

  it('falls back when the token is not set', () => {
    expect(readCssVar('--not-a-token', '#123456')).toBe('#123456');
  });
});

describe('readChartPalette', () => {
  it('resolves the five series tokens and the axis chrome', () => {
    const dark = ['#976af3', '#60a5fa', '#4ade80', '#fbbf24', '#dc2626'];
    dark.forEach((value, i) =>
      document.body.style.setProperty(`--chart-${i + 1}`, value),
    );
    document.body.style.setProperty('--border', '#44454c');
    document.body.style.setProperty('--muted-foreground', '#a1a1a1');

    const palette = readChartPalette();
    expect(palette.series).toEqual(dark);
    expect(palette.border).toBe('#44454c');
    expect(palette.mutedForeground).toBe('#a1a1a1');
  });

  it('falls back to the light tokens outside a themed document', () => {
    const palette = readChartPalette();
    expect(palette.series).toEqual([
      '#7d54d1',
      '#2563eb',
      '#079455',
      '#ca8a04',
      '#ef4444',
    ]);
    expect(palette.border).toBe('#d9d9d9');
    expect(palette.mutedForeground).toBe('#737373');
  });
});

describe('hoverColor', () => {
  it('mixes to 80% when the browser supports color-mix', () => {
    vi.stubGlobal('CSS', { supports: () => true });
    expect(hoverColor('oklch(0.6 0.2 290)')).toBe(
      'color-mix(in oklch, oklch(0.6 0.2 290) 80%, transparent)',
    );
  });

  it('falls back to an 8-digit hex without color-mix', () => {
    vi.stubGlobal('CSS', { supports: () => false });
    expect(hoverColor('#7d54d1')).toBe('#7d54d1cc');
  });

  it('keeps a non-hex colour as it is without color-mix', () => {
    vi.stubGlobal('CSS', { supports: () => false });
    expect(hoverColor('rgb(1, 2, 3)')).toBe('rgb(1, 2, 3)');
  });
});
