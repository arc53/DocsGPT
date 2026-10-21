/**
 * The agent's analytics settings (`config.analytics`): defaults, the limits
 * the server enforces, the checks the editor runs before Save so a typo
 * never comes back as a 400 naming a list index, and which source folders
 * the topic question offers.
 */
import isEqual from 'lodash/isEqual';

import type {
  AgentConfig,
  AnalyticsConfig,
  AnalyticsTopic,
  TopicFolder,
} from './types';

/**
 * The server's defaults for `ANALYTICS_MAX_TOPICS` (topics that don't
 * overlap, folders included) and `ANALYTICS_MAX_OVERLAPPING_TOPICS`.
 */
export const MAX_TOPICS = 15;
export const MAX_OVERLAPPING = 20;

export const TOPIC_NAME_MAX = 60;
/**
 * Description budgets in `units`. Topics that don't overlap share one
 * question, so each gets less room than an overlapping topic's own question.
 */
export const TOPIC_DESCRIPTION_UNITS = 150;
export const OVERLAP_DESCRIPTION_UNITS = 300;

/** The topic question's catch-all, always offered; no topic may take its name. */
export const RESERVED_TOPIC_NAME = 'none of these';

export const DEFAULT_ANALYTICS: AnalyticsConfig = {
  enabled: true,
  topics: [],
  hidden_folders: [],
  digest: false,
};

/**
 * The agent's settings, with the defaults for an agent saved before
 * analytics, or under an older shape the server no longer reads.
 */
export function analyticsOf(value?: AnalyticsConfig | null): AnalyticsConfig {
  // Only the known keys: a key of an older shape sent back would fail the
  // server's strict validation on Save.
  return {
    enabled:
      typeof value?.enabled === 'boolean'
        ? value.enabled
        : DEFAULT_ANALYTICS.enabled,
    topics: Array.isArray(value?.topics) ? value.topics : [],
    hidden_folders: Array.isArray(value?.hidden_folders)
      ? value.hidden_folders
      : [],
    digest:
      typeof value?.digest === 'boolean'
        ? value.digest
        : DEFAULT_ANALYTICS.digest,
  };
}

/**
 * Whether two agents are the same as the form saves them: a missing insights
 * block reads as the defaults, as `analyticsOf` reads it, so switching
 * insights off and on again on an agent saved before them leaves nothing to
 * save.
 */
export function sameAgent<T extends { config?: AgentConfig }>(
  a: T,
  b: T,
): boolean {
  const read = (agent: T) => ({
    ...agent,
    config: {
      ...(agent.config ?? {}),
      analytics: analyticsOf(agent.config?.analytics),
    },
  });
  return isEqual(read(a), read(b));
}

/**
 * The config to save when only the insights settings change: the saved
 * config with `analytics` replaced, so guardrails, the API write allowlist
 * and anything else stored are sent back as they are.
 */
export function withAnalytics(
  saved: AgentConfig | null | undefined,
  analytics: AnalyticsConfig,
): AgentConfig {
  return { ...(saved ?? {}), analytics };
}

/**
 * The agent config as the form saves it: a stored `analytics` block goes
 * through `analyticsOf`, so one saved under an older shape doesn't fail the
 * whole save.
 */
export function configToSave(
  config: AgentConfig | null | undefined,
): AgentConfig {
  if (!config?.analytics) return config ?? {};
  return { ...config, analytics: analyticsOf(config.analytics) };
}

/** True when nothing differs from the defaults (no topics, nothing hidden, no digest, and on). */
export function isDefaultAnalytics(value?: AnalyticsConfig | null): boolean {
  const config = analyticsOf(value);
  return (
    config.enabled &&
    config.topics.length === 0 &&
    config.hidden_folders.length === 0 &&
    !config.digest
  );
}

/** A topic's description budget, in `units`. */
export function descriptionMax(overlap: boolean): number {
  return overlap ? OVERLAP_DESCRIPTION_UNITS : TOPIC_DESCRIPTION_UNITS;
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
 * A new topic's id: 16 lowercase hex characters (the server accepts
 * `^[a-z0-9]{8,32}$`). Editing a topic keeps its id, so a renamed
 * overlapping topic keeps its history.
 */
export function newTopicId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

const sameName = (a: string, b: string) =>
  a.trim().toLocaleLowerCase() === b.trim().toLocaleLowerCase();

/** Whether `name` matches one of `others`, ignoring case and outer spaces. */
export function nameTaken(name: string, others: string[]): boolean {
  return others.some((other) => sameName(other, name));
}

/** Sorted by name, ignoring case: how the settings list each kind. */
export function byName<T extends { name: string }>(items: T[]): T[] {
  return [...items].sort((a, b) =>
    a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }),
  );
}

export type FolderView = {
  /** Folders the topic question offers, largest first. */
  shown: TopicFolder[];
  /** Folders the owner hid. */
  hidden: TopicFolder[];
  /** Folders past the limit: their questions go to "none of these". */
  cut: TopicFolder[];
};

/**
 * Which source folders the topic question offers: the server's rule
 * (`docsgpt.analytics.topics.merge`). The owner's topics that don't overlap
 * come first; folders fill what is left, largest first (`folders` is in that
 * order), skipping hidden ones and any whose name an own topic has.
 */
export function visibleFolders(
  folders: TopicFolder[],
  config: AnalyticsConfig,
  maxTopics: number,
): FolderView {
  const own = config.topics.filter((topic) => !topic.overlap);
  const room = Math.max(0, maxTopics - own.length);
  const view: FolderView = { shown: [], hidden: [], cut: [] };
  const ownNames = own.map((topic) => topic.name);
  for (const folder of folders) {
    // An own topic of the same name replaces the folder (an edited folder),
    // so it is neither shown nor offered back.
    if (nameTaken(folder.name, ownNames)) continue;
    if (nameTaken(folder.name, config.hidden_folders)) view.hidden.push(folder);
    else if (view.shown.length < room) view.shown.push(folder);
    else view.cut.push(folder);
  }
  return view;
}

/** The owner's topics of one kind. */
export function topicsOfKind(
  config: AnalyticsConfig,
  overlap: boolean,
): AnalyticsTopic[] {
  return config.topics.filter((topic) => topic.overlap === overlap);
}
