/**
 * Pure helpers for the chunk cards in the source viewer. Kept free of React so
 * the formatting rules are unit-testable in isolation.
 */

import i18next from 'i18next';

import { ChunkType } from '../settings/types';
import { formatCount, intlLocale } from '../utils/dateTimeUtils';

/** What a chunk card shows when the token count is genuinely unknown. */
export const UNKNOWN_TOKEN_COUNT = '-';

/**
 * Render a chunk's token count for display.
 *
 * The backend fills the count in for chunks that were indexed without one, but
 * stores round-trip metadata types differently: pgvector keeps JSON numbers
 * while other backends hand the same value back as a string. Both are counts,
 * so both get the UI language's thousands separators; only a missing or unusable value falls
 * back to a dash.
 */
export function formatChunkTokens(metadata: ChunkType['metadata']): string {
  const raw = metadata?.token_count;
  const count = typeof raw === 'string' ? Number(raw.trim()) : raw;
  if (typeof count !== 'number' || !Number.isFinite(count) || count <= 0) {
    return UNKNOWN_TOKEN_COUNT;
  }
  return formatCount(count);
}

/**
 * The chunk count beside the search and in the byline: short where the
 * language has a short form ("1.2K", "1,2 тыс.", "150万"), grouped digits where
 * it has none (de and ja below 10,000: "1.234").
 *
 * @param total The chunk count.
 * @param language An app language code; defaults to the current one.
 * @returns The formatted count.
 */
export function abbreviateCount(
  total: number,
  language: string = i18next.language,
): string {
  return new Intl.NumberFormat(intlLocale(language), {
    notation: 'compact',
    useGrouping: 'always',
  }).format(total);
}

/**
 * The text a chunk tile previews: the stored text with markdown heading
 * markers stripped, table-of-contents dot leaders collapsed to "…", runs of
 * whitespace folded and line breaks joined with " · ". Display only; the
 * stored text and the editor keep the original.
 */
export function chunkPreviewText(text: string): string {
  return (text ?? '')
    .split(/\r?\n/)
    .map((line) =>
      line
        .replace(/^\s*#+\s*/, '')
        .replace(/\.{4,}/g, ' … ')
        .replace(/[ \t]+/g, ' ')
        .trim(),
    )
    .filter(Boolean)
    .join(' · ');
}
