import { describe, expect, it } from 'vitest';

import { formatChunkTokens, UNKNOWN_TOKEN_COUNT } from './chunkUtils';

type ChunkMetadata = Parameters<typeof formatChunkTokens>[0];

describe('formatChunkTokens', () => {
  it('formats a numeric count with separators', () => {
    expect(formatChunkTokens({ token_count: 1234 })).toBe(
      (1234).toLocaleString(),
    );
  });

  it('formats a count a store handed back as a string', () => {
    expect(formatChunkTokens({ token_count: '1234' })).toBe(
      (1234).toLocaleString(),
    );
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
