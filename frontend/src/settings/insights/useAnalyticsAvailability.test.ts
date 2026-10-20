import { MAX_TAGS, MAX_TOPICS } from '../../agents/analyticsConfig';
import { analyticsAvailability } from './useAnalyticsAvailability';

describe('analyticsAvailability', () => {
  it('reads the switch and the limits off /api/config', () => {
    expect(
      analyticsAvailability({
        decision_analytics_enabled: true,
        analytics_max_topics: 8,
        analytics_max_tags: 5,
      }),
    ).toEqual({ enabled: true, maxTopics: 8, maxTags: 5 });
  });

  it('keeps a tag limit of 0, which the server allows to turn tags off', () => {
    expect(analyticsAvailability({ analytics_max_tags: 0 }).maxTags).toBe(0);
  });

  it('falls back to the defaults for a missing or invalid limit', () => {
    expect(
      analyticsAvailability({
        analytics_max_topics: 0,
        analytics_max_tags: -1,
      }),
    ).toEqual({ enabled: false, maxTopics: MAX_TOPICS, maxTags: MAX_TAGS });
  });
});
