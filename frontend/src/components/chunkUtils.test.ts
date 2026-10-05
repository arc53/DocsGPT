import { afterEach, describe, expect, it } from 'vitest';

import i18next from 'i18next';

import {
  abbreviateCount,
  chunkPreviewText,
  formatChunkTokens,
  UNKNOWN_TOKEN_COUNT,
} from './chunkUtils';

type ChunkMetadata = Parameters<typeof formatChunkTokens>[0];

describe('formatChunkTokens', () => {
  const language = i18next.language;
  afterEach(() => {
    i18next.language = language;
  });

  it('formats a numeric count with separators', () => {
    i18next.language = 'en';
    expect(formatChunkTokens({ token_count: 1234 })).toBe('1,234');
  });

  it('formats a count a store handed back as a string', () => {
    i18next.language = 'en';
    expect(formatChunkTokens({ token_count: '1234' })).toBe('1,234');
  });

  // Bugs row 8: the app language's separators, not the browser's.
  it('groups in the app language', () => {
    i18next.language = 'de';
    expect(formatChunkTokens({ token_count: 11420 })).toBe('11.420');
  });

  it('falls back to a dash when the count is unusable', () => {
    for (const token_count of [undefined, 0, -1, 'abc', '']) {
      expect(formatChunkTokens({ token_count })).toBe(UNKNOWN_TOKEN_COUNT);
    }
  });

  it('tolerates metadata the store returned as null', () => {
    expect(formatChunkTokens(null as unknown as ChunkMetadata)).toBe(
      UNKNOWN_TOKEN_COUNT,
    );
  });
});

describe('chunkPreviewText', () => {
  it('strips markdown heading markers and folds line breaks', () => {
    expect(
      chunkPreviewText('##### Taxation and\n\n##### Customs Union\n# 2026'),
    ).toBe('Taxation and · Customs Union · 2026');
  });

  it('collapses dot leaders and runs of whitespace', () => {
    expect(chunkPreviewText('List of Tables......................12')).toBe(
      'List of Tables … 12',
    );
    expect(chunkPreviewText('a   b\t\tc')).toBe('a b c');
  });

  it('keeps ordinary text, an ellipsis and a hash inside a line', () => {
    expect(chunkPreviewText('Wait... issue #12 is open.')).toBe(
      'Wait... issue #12 is open.',
    );
    expect(chunkPreviewText('')).toBe('');
  });
});

describe('abbreviateCount', () => {
  it('shortens where the language has a short form', () => {
    expect(abbreviateCount(1234, 'en')).toBe('1.2K');
    expect(abbreviateCount(1500000, 'en')).toBe('1.5M');
    expect(abbreviateCount(1234, 'ru')).toBe('1,2\u00a0тыс.');
    expect(abbreviateCount(1500000, 'jp')).toBe('150万');
  });

  // de and ja have no compact thousands: the digits still group.
  it('groups the digits where it has none', () => {
    expect(abbreviateCount(1234, 'de')).toBe('1.234');
    expect(abbreviateCount(1234, 'jp')).toBe('1,234');
    expect(abbreviateCount(1500000, 'de')).toBe('1,5\u00a0Mio.');
  });

  it('leaves counts under a thousand as they are', () => {
    expect(abbreviateCount(999, 'en')).toBe('999');
    expect(abbreviateCount(0, 'zhTW')).toBe('0');
  });
});
