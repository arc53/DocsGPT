import apiClient, { baseURL } from '../client';

/**
 * Background jobs, presence, Web Push subscriptions and unread marks. The
 * paths live here rather than in `endpoints.ts`: they are one feature's.
 */
export const BACKGROUND_PATHS = {
  JOBS: (conversationId: string) =>
    `/api/background_jobs?conversation_id=${encodeURIComponent(conversationId)}`,
  JOB: (id: string) => `/api/background_jobs/${encodeURIComponent(id)}`,
  JOB_CANCEL: (id: string) =>
    `/api/background_jobs/${encodeURIComponent(id)}/cancel`,
  PRESENCE: '/api/presence',
  PUSH_PUBLIC_KEY: '/api/push/public_key',
  PUSH_SUBSCRIPTIONS: '/api/push/subscriptions',
  CONVERSATION_READ: (id: string) =>
    `/api/conversations/${encodeURIComponent(id)}/read`,
} as const;

export type BackgroundJobStatus =
  'working' | 'completed' | 'failed' | 'cancelled' | 'lost';

export type BackgroundJobProgress = {
  percent?: number;
  last?: string;
  updated_at?: string;
};

/** `job_summary` on the backend (`docsgpt/background/service.py`). */
export type BackgroundJobSummary = {
  job_id: string;
  conversation_id?: string | null;
  tool_name?: string;
  action_name?: string;
  status: BackgroundJobStatus;
  status_message?: string | null;
  progress?: BackgroundJobProgress;
  output_tail?: string | null;
  elapsed_s?: number;
  started_at?: string | null;
  finished_at?: string | null;
  auto_resume?: boolean;
  cancel_requested?: boolean;
  /** A finished job's error message (the single-job route only). */
  error?: string;
};

export type PresenceReport = {
  tab_id: string;
  conversation_id: string | null;
  visible: boolean;
  closing?: boolean;
};

export type PushConfig = { enabled: boolean; public_key: string | null };

const okJson = async <T>(response: Response): Promise<T> => {
  if (!response || response.ok === false) {
    throw new Error(`HTTP ${response?.status ?? 'error'}`);
  }
  return (await response.json()) as T;
};

const backgroundService = {
  /** The conversation's jobs, newest first, without result bodies. */
  listJobs: async (
    conversationId: string,
    token: string | null,
  ): Promise<BackgroundJobSummary[]> =>
    (
      await okJson<{ jobs?: BackgroundJobSummary[] }>(
        await apiClient.get(BACKGROUND_PATHS.JOBS(conversationId), token),
      )
    ).jobs ?? [],

  getJob: async (
    jobId: string,
    token: string | null,
  ): Promise<BackgroundJobSummary> =>
    okJson(await apiClient.get(BACKGROUND_PATHS.JOB(jobId), token)),

  cancelJob: async (
    jobId: string,
    token: string | null,
  ): Promise<BackgroundJobSummary> =>
    okJson(await apiClient.post(BACKGROUND_PATHS.JOB_CANCEL(jobId), {}, token)),

  /**
   * Report what this tab shows. A closing report rides `keepalive` so it
   * still goes out while the page unloads; without a token (auth off)
   * `sendBeacon` carries it.
   */
  reportPresence: (report: PresenceReport, token: string | null): void => {
    const url = `${baseURL}${BACKGROUND_PATHS.PRESENCE}`;
    const body = JSON.stringify(report);
    if (
      report.closing &&
      !token &&
      typeof navigator !== 'undefined' &&
      typeof navigator.sendBeacon === 'function' &&
      navigator.sendBeacon(url, new Blob([body], { type: 'text/plain' }))
    ) {
      return;
    }
    try {
      void fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body,
        keepalive: Boolean(report.closing),
      }).catch(() => undefined);
    } catch {
      // A report is best-effort; the server lets a silent tab expire.
    }
  },

  getPushConfig: async (token: string | null): Promise<PushConfig> =>
    okJson(await apiClient.get(BACKGROUND_PATHS.PUSH_PUBLIC_KEY, token)),

  savePushSubscription: async (
    subscription: PushSubscriptionJSON,
    token: string | null,
  ): Promise<void> => {
    await okJson(
      await apiClient.post(
        BACKGROUND_PATHS.PUSH_SUBSCRIPTIONS,
        subscription,
        token,
      ),
    );
  },

  deletePushSubscription: async (
    endpoint: string,
    token: string | null,
  ): Promise<void> => {
    await okJson(
      await apiClient.delete(BACKGROUND_PATHS.PUSH_SUBSCRIPTIONS, token, {
        endpoint,
      }),
    );
  },

  /**
   * Forget a subscription while the page goes away (sign-out): a
   * `keepalive` request, best-effort, never awaited.
   */
  forgetPushSubscriptionOnExit: (
    endpoint: string,
    token: string | null,
  ): void => {
    try {
      void fetch(`${baseURL}${BACKGROUND_PATHS.PUSH_SUBSCRIPTIONS}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ endpoint }),
        keepalive: true,
      }).catch(() => undefined);
    } catch {
      // The browser's own unsubscribe still retires the endpoint.
    }
  },

  markConversationRead: async (
    conversationId: string,
    token: string | null,
  ): Promise<void> => {
    await okJson(
      await apiClient.post(
        BACKGROUND_PATHS.CONVERSATION_READ(conversationId),
        {},
        token,
      ),
    );
  },
};

export default backgroundService;
