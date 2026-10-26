import { describe, expect, it } from 'vitest';

import {
  MAX_CONTEXT_WINDOW_LIMIT,
  MIN_CONTEXT_WINDOW_LIMIT,
  isContextLimitInvalid,
  parseContextLimit,
} from './contextLimit';

describe('context limit', () => {
  it('treats an unset limit as valid', () => {
    expect(isContextLimitInvalid(undefined)).toBe(false);
    expect(isContextLimitInvalid(null)).toBe(false);
  });

  it('accepts the bounds and rejects what is outside them', () => {
    expect(isContextLimitInvalid(MIN_CONTEXT_WINDOW_LIMIT)).toBe(false);
    expect(isContextLimitInvalid(MAX_CONTEXT_WINDOW_LIMIT)).toBe(false);
    expect(isContextLimitInvalid(MIN_CONTEXT_WINDOW_LIMIT - 1)).toBe(true);
    expect(isContextLimitInvalid(MAX_CONTEXT_WINDOW_LIMIT + 1)).toBe(true);
    expect(isContextLimitInvalid(32000.5)).toBe(true);
  });

  it('reads an empty field as no limit', () => {
    expect(parseContextLimit('')).toBeNull();
    expect(parseContextLimit('  ')).toBeNull();
    expect(parseContextLimit('32000')).toBe(32000);
  });
});
