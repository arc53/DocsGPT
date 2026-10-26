import { describe, expect, it } from 'vitest';

import type { Model } from '../models/types';
import {
  MAX_CONTEXT_WINDOW_LIMIT,
  MIN_CONTEXT_WINDOW_LIMIT,
  MIN_HISTORY_TOKEN_LIMIT,
  contextLimitMax,
  historyLimitMax,
  isContextLimitInvalid,
  isHistoryLimitInvalid,
  largestModelWindow,
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

const model = (id: string, contextWindow: number) =>
  ({
    id,
    value: id,
    provider: 'openai',
    display_name: id.toUpperCase(),
    context_window: contextWindow,
    supported_attachment_types: [],
    supports_tools: true,
    supports_structured_output: true,
    supports_streaming: true,
  }) as Model;

describe('model window', () => {
  const models = [model('a', 128_000), model('b', 1_000_000), model('c', 0)];

  it('is the largest window among the given models, with its name', () => {
    expect(largestModelWindow(models, ['a', 'b'])).toEqual({
      tokens: 1_000_000,
      name: 'B',
    });
    expect(largestModelWindow(models, new Set(['a']))).toEqual({
      tokens: 128_000,
      name: 'A',
    });
  });

  it('is unknown without a model that reports one', () => {
    expect(largestModelWindow(models, [])).toBeNull();
    expect(largestModelWindow(models, ['c', 'missing'])).toBeNull();
  });

  it('bounds the context limit', () => {
    const window = { tokens: 128_000, name: 'A' };
    expect(contextLimitMax(window)).toBe(128_000);
    expect(contextLimitMax(null)).toBe(MAX_CONTEXT_WINDOW_LIMIT);
    expect(isContextLimitInvalid(128_000, window)).toBe(false);
    expect(isContextLimitInvalid(128_001, window)).toBe(true);
    // A window under the floor still leaves the floor valid.
    expect(contextLimitMax({ tokens: 8000, name: 'S' })).toBe(
      MIN_CONTEXT_WINDOW_LIMIT,
    );
  });

  it('reads a switched-on but empty field as invalid', () => {
    expect(isContextLimitInvalid(Number.NaN)).toBe(true);
    expect(isHistoryLimitInvalid(Number.NaN, null, null)).toBe(true);
  });
});

describe('history limit', () => {
  const window = { tokens: 128_000, name: 'A' };

  it('treats an unset limit as valid', () => {
    expect(isHistoryLimitInvalid(null, null, window)).toBe(false);
    expect(isHistoryLimitInvalid(undefined, 32_000, window)).toBe(false);
  });

  it('stays below the context limit, or the window without one', () => {
    expect(historyLimitMax(32_000, window)).toBe(31_999);
    expect(historyLimitMax(null, window)).toBe(127_999);
    // An invalid context limit leaves the window as the bound.
    expect(historyLimitMax(Number.NaN, window)).toBe(127_999);
    expect(isHistoryLimitInvalid(32_000, 32_000, window)).toBe(true);
    expect(isHistoryLimitInvalid(31_999, 32_000, window)).toBe(false);
  });

  it('has a floor', () => {
    expect(isHistoryLimitInvalid(MIN_HISTORY_TOKEN_LIMIT, null, window)).toBe(
      false,
    );
    expect(
      isHistoryLimitInvalid(MIN_HISTORY_TOKEN_LIMIT - 1, null, window),
    ).toBe(true);
  });
});
