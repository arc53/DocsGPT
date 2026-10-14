import type { PlannedWindow } from '../../activity/calendar/types';
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

  /** Planned runs, past runs, monitors and syncs of a window (at most 62 days). */
  planned: async (
    from: Date,
    to: Date,
    token: string | null,
  ): Promise<PlannedWindow> => {
    const r = (await apiClient.get(
      endpoints.USER.ACTIVITY_PLANNED(from.toISOString(), to.toISOString()),
      token,
    )) as Response;
    if (!r.ok) throw new Error(`Calendar failed: ${r.status}`);
    return (await r.json()) as PlannedWindow;
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
