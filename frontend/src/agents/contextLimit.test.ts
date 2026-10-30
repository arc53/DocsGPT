import { describe, expect, it } from 'vitest';

import type { Model } from '../models/types';
import {
  MAX_CONTEXT_WINDOW_LIMIT,
  MIN_CONTEXT_WINDOW_LIMIT,
  MIN_HISTORY_TOKEN_LIMIT,
  contextLimitAboveWindow,
  defaultContextLimit,
  defaultHistoryLimit,
  historyLimitAboveWindow,
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

  it('flags a context limit past the window without making it invalid', () => {
    const window = { tokens: 128_000, name: 'A' };
    expect(isContextLimitInvalid(200_000)).toBe(false);
    expect(contextLimitAboveWindow(128_000, window)).toBe(false);
    expect(contextLimitAboveWindow(128_001, window)).toBe(true);
    expect(contextLimitAboveWindow(200_000, null)).toBe(false);
    expect(contextLimitAboveWindow(null, window)).toBe(false);
    // An invalid value shows its error, not the note.
    expect(contextLimitAboveWindow(Number.NaN, window)).toBe(false);
    // The floor itself is past a small model's window.
    expect(
      contextLimitAboveWindow(MIN_CONTEXT_WINDOW_LIMIT, {
        tokens: 8000,
        name: 'S',
      }),
    ).toBe(true);
  });

  it('switches on at a value the window takes', () => {
    expect(defaultContextLimit(null)).toBe(100_000);
    expect(defaultContextLimit({ tokens: 1_000_000, name: 'B' })).toBe(100_000);
    expect(defaultContextLimit({ tokens: 32_000, name: 'C' })).toBe(32_000);
    expect(defaultContextLimit({ tokens: 8000, name: 'S' })).toBe(
      MIN_CONTEXT_WINDOW_LIMIT,
    );
  });

  it('reads a switched-on but empty field as invalid', () => {
    expect(isContextLimitInvalid(Number.NaN)).toBe(true);
    expect(isHistoryLimitInvalid(Number.NaN, null)).toBe(true);
  });
});

describe('history limit', () => {
  const window = { tokens: 128_000, name: 'A' };

  it('treats an unset limit as valid', () => {
    expect(isHistoryLimitInvalid(null, null)).toBe(false);
    expect(isHistoryLimitInvalid(undefined, 32_000)).toBe(false);
  });

  it('stays below the context limit', () => {
    expect(historyLimitMax(32_000)).toBe(31_999);
    expect(historyLimitMax(null)).toBe(MAX_CONTEXT_WINDOW_LIMIT);
    // An invalid context limit leaves the server's bound.
    expect(historyLimitMax(Number.NaN)).toBe(MAX_CONTEXT_WINDOW_LIMIT);
    expect(isHistoryLimitInvalid(32_000, 32_000)).toBe(true);
    expect(isHistoryLimitInvalid(31_999, 32_000)).toBe(false);
    expect(isHistoryLimitInvalid(200_000, null)).toBe(false);
  });

  it('flags a history limit at the window without making it invalid', () => {
    expect(historyLimitAboveWindow(127_999, window)).toBe(false);
    expect(historyLimitAboveWindow(128_000, window)).toBe(true);
    expect(historyLimitAboveWindow(128_000, null)).toBe(false);
    expect(historyLimitAboveWindow(Number.NaN, window)).toBe(false);
  });

  it('switches on below the context limit and the window', () => {
    expect(defaultHistoryLimit(null, window)).toBe(8000);
    expect(defaultHistoryLimit(null, { tokens: 8000, name: 'S' })).toBe(7999);
    // The context limit's floor is above the default, so only the window
    // lowers it.
    expect(defaultHistoryLimit(MIN_CONTEXT_WINDOW_LIMIT, null)).toBe(8000);
    // Never below the floor, even where that is past a tiny window.
    expect(defaultHistoryLimit(null, { tokens: 2000, name: 'T' })).toBe(
      MIN_HISTORY_TOKEN_LIMIT,
    );
  });

  it('has a floor', () => {
    expect(isHistoryLimitInvalid(MIN_HISTORY_TOKEN_LIMIT, null)).toBe(false);
    expect(isHistoryLimitInvalid(MIN_HISTORY_TOKEN_LIMIT - 1, null)).toBe(true);
  });
});
