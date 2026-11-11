import { describe, expect, it } from 'vitest';

import { cleanStarters, MAX_STARTERS } from './starters';

describe('cleanStarters', () => {
  it('trims, drops empty and repeated questions, and keeps the order', () => {
    expect(
      cleanStarters(['  Run due diligence ', '', 'Which DPAs?', 'which dpas?']),
    ).toEqual(['Run due diligence', 'Which DPAs?']);
  });

  it(`keeps at most ${MAX_STARTERS}`, () => {
    expect(cleanStarters(['a', 'b', 'c', 'd', 'e'])).toEqual([
      'a',
      'b',
      'c',
      'd',
    ]);
  });

  it('reads a missing or malformed list as none', () => {
    expect(cleanStarters(undefined)).toEqual([]);
    expect(cleanStarters(null)).toEqual([]);
    expect(cleanStarters(['ok', 3 as unknown as string])).toEqual(['ok']);
  });
});
