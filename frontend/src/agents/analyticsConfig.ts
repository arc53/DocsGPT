/**
 * The agent's analytics settings (`config.analytics`): defaults, the limits
 * the server enforces, and the checks the editor runs before Save so a typo
 * never comes back as a 400 naming a list index.
 */
import type { AnalyticsConfig, AnalyticsTopic } from './types';

/** The server's defaults for `ANALYTICS_MAX_TOPICS` and `ANALYTICS_MAX_TAGS`. */
export const MAX_TOPICS = 15;
export const MAX_TAGS = 20;

export const TOPIC_NAME_MAX = 60;
/** In `units`, since every topic's text is part of the model's question. */
export const TOPIC_DESCRIPTION_UNITS = 150;
export const TAG_NAME_MAX = 60;
export const TAG_DESCRIPTION_MAX = 300;

/** Topics below this count are not asked: one topic sorts nothing. */
export const MIN_CUSTOM_TOPICS = 2;

/** The topic question's catch-all, always offered; no topic may take its name. */
export const RESERVED_TOPIC_NAME = 'none of these';

export const DEFAULT_ANALYTICS: AnalyticsConfig = {
  enabled: true,
  topics: { mode: 'auto', items: [] },
  tags: [],
  digest: false,
};

/** The agent's settings, with the defaults for an agent saved before analytics. */
export function analyticsOf(value?: AnalyticsConfig | null): AnalyticsConfig {
  return {
    ...DEFAULT_ANALYTICS,
    ...(value ?? {}),
    topics: { ...DEFAULT_ANALYTICS.topics, ...(value?.topics ?? {}) },
    tags: value?.tags ?? [],
  };
}

/** True when nothing differs from the defaults (no topics, tags or digest, and on). */
export function isDefaultAnalytics(value?: AnalyticsConfig | null): boolean {
  const config = analyticsOf(value);
  return (
    config.enabled &&
    config.topics.mode === 'auto' &&
    config.topics.items.length === 0 &&
    config.tags.length === 0 &&
    !config.digest
  );
}

/**
 * The length of `text` in Latin-character units, as the server counts it
 * (`docsgpt.analytics.schema.units`): a CJK, Hangul or full-width character
 * counts 3 and a Cyrillic one 1.2, because the model reads them as that many
 * more tokens.
 */
export function units(text: string): number {
  let total = 0;
  for (const ch of text) {
    const code = ch.codePointAt(0) ?? 0;
    if (
      (code >= 0x2e80 && code <= 0x9fff) ||
      (code >= 0xac00 && code <= 0xd7af) ||
      (code >= 0xf900 && code <= 0xfaff) ||
      (code >= 0xff00 && code <= 0xffef)
    )
      total += 3;
    else if (code >= 0x0400 && code <= 0x04ff) total += 1.2;
    else total += 1;
  }
  return total;
}

/**
 * A new tag's id: 16 lowercase hex characters (the server accepts
 * `^[a-z0-9]{8,32}$`). Editing a tag keeps its id, so a renamed tag keeps
 * its history.
 */
export function newTagId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

const sameName = (a: string, b: string) =>
  a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();

/** Whether `name` matches one of `others`, ignoring case and outer spaces. */
export function nameTaken(name: string, others: string[]): boolean {
  return others.some((other) => sameName(other, name));
}

/**
 * Suggested topics appended to the list: those whose name is not there yet,
 * up to the limit. Existing rows are never changed.
 *
 * Returns:
 *   The new list and why nothing (or not everything) was added: `none` when
 *   there was nothing to suggest, `noNew` when every suggestion is listed,
 *   `full` when the limit cut some off.
 */
export function appendSuggestions(
  items: AnalyticsTopic[],
  suggestions: AnalyticsTopic[],
  max: number,
): {
  items: AnalyticsTopic[];
  note: 'none' | 'noNew' | 'full' | null;
} {
  if (suggestions.length === 0) return { items, note: 'none' };
  const fresh: AnalyticsTopic[] = [];
  for (const suggestion of suggestions) {
    const name = suggestion.name.trim();
    if (!name || sameName(name, RESERVED_TOPIC_NAME)) continue;
    if (
      nameTaken(
        name,
        [...items, ...fresh].map((item) => item.name),
      )
    )
      continue;
    fresh.push({ name, description: suggestion.description ?? '' });
  }
  if (fresh.length === 0) return { items, note: 'noNew' };
  const room = Math.max(0, max - items.length);
  return {
    items: [...items, ...fresh.slice(0, room)],
    note: fresh.length > room ? 'full' : null,
  };
}
