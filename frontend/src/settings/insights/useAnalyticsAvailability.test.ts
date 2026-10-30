import { act, createElement } from 'react';
import { createRoot } from 'react-dom/client';

const store = vi.hoisted(() => ({
  preference: {
    analyticsEnabled: true,
    analyticsMaxTopics: 8,
    analyticsMaxOverlapping: 0,
  },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store),
}));
const getConfig = vi.hoisted(() => vi.fn());
vi.mock('../../api/services/userService', () => ({ default: { getConfig } }));

import { MAX_OVERLAPPING, MAX_TOPICS } from '../../agents/analyticsConfig';
import {
  analyticsAvailability,
  useAnalyticsAvailability,
} from './useAnalyticsAvailability';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// FX-9: one read of /api/config at start, into the store; a page reads it
// from there instead of fetching it again on every mount.
describe('useAnalyticsAvailability', () => {
  it('reads the switch and the limits from the store, asking the server nothing', () => {
    let seen: unknown;
    function Probe() {
      seen = useAnalyticsAvailability();
      return null;
    }
    const container = document.createElement('div');
    const root = createRoot(container);
    act(() => root.render(createElement(Probe)));
    expect(seen).toEqual({ enabled: true, maxTopics: 8, maxOverlapping: 0 });
    expect(getConfig).not.toHaveBeenCalled();
    act(() => root.unmount());
  });
});

describe('analyticsAvailability', () => {
  it('reads the switch and the limits off /api/config', () => {
    expect(
      analyticsAvailability({
        decision_analytics_enabled: true,
        analytics_max_topics: 8,
        analytics_max_overlapping_topics: 5,
      }),
    ).toEqual({ enabled: true, maxTopics: 8, maxOverlapping: 5 });
  });

  it('keeps an overlap limit of 0, which the server allows to turn overlapping topics off', () => {
    expect(
      analyticsAvailability({ analytics_max_overlapping_topics: 0 })
        .maxOverlapping,
    ).toBe(0);
  });

  it('falls back to the defaults for a missing or invalid limit', () => {
    expect(
      analyticsAvailability({
        analytics_max_topics: 0,
        analytics_max_overlapping_topics: -1,
      }),
    ).toEqual({
      enabled: false,
      maxTopics: MAX_TOPICS,
      maxOverlapping: MAX_OVERLAPPING,
    });
  });
});
