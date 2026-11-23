/** The server keeps at most this many starters per agent. */
export const MAX_STARTERS = 4;
/** The server refuses a longer starter. */
export const MAX_STARTER_LENGTH = 200;

/**
 * An agent's starters as the server stores them: trimmed, empty ones and
 * repeats (ignoring case) dropped, in order, at most `MAX_STARTERS`. A
 * missing or malformed list reads as none.
 */
export function cleanStarters(starters: unknown): string[] {
  if (!Array.isArray(starters)) return [];
  const seen = new Set<string>();
  const cleaned: string[] = [];
  for (const entry of starters) {
    if (typeof entry !== 'string') continue;
    const text = entry.trim();
    const folded = text.toLowerCase();
    if (!text || seen.has(folded)) continue;
    seen.add(folded);
    cleaned.push(text);
    if (cleaned.length === MAX_STARTERS) break;
  }
  return cleaned;
}
