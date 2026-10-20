import { useSelector } from 'react-redux';

import { MAX_TAGS, MAX_TOPICS } from '../../agents/analyticsConfig';
import {
  selectAnalyticsEnabled,
  selectAnalyticsMaxTags,
  selectAnalyticsMaxTopics,
} from '../../preferences/preferenceSlice';

/**
 * Whether the decision model may label conversations on this server, and the
 * agent editor's topic and tag limits, from /api/config.
 */
export type AnalyticsAvailability = {
  enabled: boolean;
  maxTopics: number;
  maxTags: number;
};

// The server allows ANALYTICS_MAX_TAGS=0 (tags off), but never fewer than 2 topics.
const limit = (value: unknown, fallback: number, min = 1): number =>
  typeof value === 'number' && Number.isInteger(value) && value >= min
    ? value
    : fallback;

/** Read `AnalyticsAvailability` off an /api/config response; off without the flag. */
export function analyticsAvailability(config: unknown): AnalyticsAvailability {
  const c = (config ?? {}) as Record<string, unknown>;
  return {
    enabled: c.decision_analytics_enabled === true,
    maxTopics: limit(c.analytics_max_topics, MAX_TOPICS),
    maxTags: limit(c.analytics_max_tags, MAX_TAGS, 0),
  };
}

/**
 * `AnalyticsAvailability` for this server, from the store, which reads
 * /api/config once at start (`useDataInitializer`): off, with the default
 * limits, until the config loads, and if it fails.
 */
export function useAnalyticsAvailability(): AnalyticsAvailability {
  return {
    enabled: useSelector(selectAnalyticsEnabled),
    maxTopics: useSelector(selectAnalyticsMaxTopics),
    maxTags: useSelector(selectAnalyticsMaxTags),
  };
}
