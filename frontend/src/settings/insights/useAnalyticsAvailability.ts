import { useEffect, useState } from 'react';

import userService from '../../api/services/userService';
import { MAX_TAGS, MAX_TOPICS } from '../../agents/analyticsConfig';

/**
 * Whether the decision model may label conversations on this server, and the
 * agent editor's topic and tag limits, from /api/config.
 */
export type AnalyticsAvailability = {
  enabled: boolean;
  maxTopics: number;
  maxTags: number;
};

export const NO_ANALYTICS: AnalyticsAvailability = {
  enabled: false,
  maxTopics: MAX_TOPICS,
  maxTags: MAX_TAGS,
};

const limit = (value: unknown, fallback: number): number =>
  typeof value === 'number' && Number.isInteger(value) && value > 0
    ? value
    : fallback;

/** Read `AnalyticsAvailability` off an /api/config response; off without the flag. */
export function analyticsAvailability(config: unknown): AnalyticsAvailability {
  const c = (config ?? {}) as Record<string, unknown>;
  return {
    enabled: c.decision_analytics_enabled === true,
    maxTopics: limit(c.analytics_max_topics, MAX_TOPICS),
    maxTags: limit(c.analytics_max_tags, MAX_TAGS),
  };
}

/**
 * `AnalyticsAvailability` for this server, read once per mount; off (and the
 * default limits) until /api/config answers, and if it fails.
 */
export function useAnalyticsAvailability(): AnalyticsAvailability & {
  loaded: boolean;
} {
  const [state, setState] = useState({ ...NO_ANALYTICS, loaded: false });
  useEffect(() => {
    let cancelled = false;
    // Started inside the chain, so a missing config reads as off.
    Promise.resolve()
      .then(() => userService.getConfig())
      .then((response: Response) => response.json())
      .then((config: unknown) => {
        if (!cancelled)
          setState({ ...analyticsAvailability(config), loaded: true });
      })
      .catch(() => {
        if (!cancelled) setState({ ...NO_ANALYTICS, loaded: true });
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return state;
}
