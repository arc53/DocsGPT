import type { PlannedWindow } from '../../activity/calendar/types';
import type { HistoryPage, HistoryQuery } from '../../activity/historyTypes';
import type { NowSnapshot } from '../../activity/types';
import apiClient from '../client';
import endpoints from '../endpoints';

const activityService = {
  /** What runs now, what waits for the user, and what runs in the next day. */
  now: async (token: string | null): Promise<NowSnapshot> => {
    const r = (await apiClient.get(
      endpoints.USER.ACTIVITY_NOW,
      token,
    )) as Response;
    if (!r.ok) throw new Error(`Activity failed: ${r.status}`);
    return (await r.json()) as NowSnapshot;
  },

  /**
   * Planned runs, past runs, monitors and syncs of a window (at most 62
   * days). The browser's time zone goes along: the server sums up a frequent
   * schedule per day in it, so its days are the ones the Calendar draws.
   */
  planned: async (
    from: Date,
    to: Date,
    token: string | null,
  ): Promise<PlannedWindow> => {
    const r = (await apiClient.get(
      endpoints.USER.ACTIVITY_PLANNED(
        from.toISOString(),
        to.toISOString(),
        Intl.DateTimeFormat().resolvedOptions().timeZone,
      ),
      token,
    )) as Response;
    if (!r.ok) throw new Error(`Calendar failed: ${r.status}`);
    return (await r.json()) as PlannedWindow;
  },

  /** One page of finished runs of every kind, newest first. */
  history: async (
    query: HistoryQuery,
    token: string | null,
  ): Promise<HistoryPage> => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== '') params.set(key, String(value));
    }
    const r = (await apiClient.get(
      endpoints.USER.ACTIVITY_HISTORY(params.toString()),
      token,
    )) as Response;
    if (!r.ok) throw new Error(`History failed: ${r.status}`);
    return (await r.json()) as HistoryPage;
  },

  /** Ask a running chat answer to stop; it keeps what it wrote. */
  stopMessage: async (
    messageId: string,
    token: string | null,
  ): Promise<void> => {
    const r = (await apiClient.post(
      endpoints.USER.MESSAGE_CANCEL(messageId),
      {},
      token,
    )) as Response;
    if (!r.ok) throw new Error(`Stop failed: ${r.status}`);
  },
};

export default activityService;
