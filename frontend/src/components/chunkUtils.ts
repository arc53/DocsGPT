/**
 * Pure helpers for the chunk cards in the source viewer. Kept free of React so
 * the formatting rules are unit-testable in isolation.
 */

import { ChunkType } from '../settings/types';

/** What a chunk card shows when the token count is genuinely unknown. */
export const UNKNOWN_TOKEN_COUNT = '-';

/**
 * Render a chunk's token count for display.
 *
 * The backend fills the count in for chunks that were indexed without one, but
 * stores round-trip metadata types differently: pgvector keeps JSON numbers
 * while other backends hand the same value back as a string. Both are counts,
 * so both get thousands separators; only a missing or unusable value falls
 * back to a dash.
 */
export function formatChunkTokens(metadata: ChunkType['metadata']): string {
  const raw = metadata?.token_count;
  const count = typeof raw === 'string' ? Number(raw.trim()) : raw;
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) {
    return UNKNOWN_TOKEN_COUNT;
  }
  return count.toLocaleString();
}
