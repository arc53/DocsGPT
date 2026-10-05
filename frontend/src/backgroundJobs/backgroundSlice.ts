import {
  createAsyncThunk,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import backgroundService, {
  type BackgroundJobProgress,
  type BackgroundJobStatus,
  type BackgroundJobSummary,
  type PushConfig,
} from '../api/services/backgroundService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import {
  appendConversations,
  receiveConversations,
} from '../preferences/preferenceSlice';
import type { ConversationSummary } from '../preferences/types';
import {
  loadDismissed,
  saveDismissed,
  type DismissedEntry,
} from '../notifications/dismissedPersistence';

const DISMISSED_NOTIFICATIONS_STORAGE_KEY =
  'docsgpt:dismissedConversationNotifications';
const DISMISSED_NOTIFICATIONS_TTL_MS = 24 * 60 * 60 * 1000;
const DISMISSED_NOTIFICATIONS_CAP = 200;

/** What the job card knows about one job: merged from fetches and `job.updated`. */
export type BackgroundJob = Partial<BackgroundJobSummary> & {
  job_id: string;
  status: BackgroundJobStatus;
  /** Wallclock ms of the last fetch or event, for the card's refresh. */
  receivedAt: number;
};

export type BackgroundState = {
  jobs: Record<string, BackgroundJob>;
  /**
   * Jobs this user can't read (another user's, in a shared conversation):
   * their cards show the saved outcome and neither poll nor offer Cancel.
   */
  unavailableJobs: Record<string, true>;
  /** When each conversation's job list was last asked for, to space the polls. */
  jobListRequestedAt: Record<string, number>;
  /** Conversations with a message the user has not seen. */
  unread: Record<string, true>;
  /** Server Web Push configuration; null until fetched. */
  pushConfig: PushConfig | null;
  /** The in-context "Get notified when it's done?" prompt is showing. */
  pushPromptOpen: boolean;
  /**
   * `notification.created` event ids whose toast was closed, opened or timed
   * out, persisted so the stream's backlog replay on reload doesn't re-pop them.
   */
  dismissedNotifications: DismissedEntry[];
};

const initialState: BackgroundState = {
  jobs: {},
  unavailableJobs: {},
  jobListRequestedAt: {},
  unread: {},
  pushConfig: null,
  pushPromptOpen: false,
  dismissedNotifications: loadDismissed(
    DISMISSED_NOTIFICATIONS_STORAGE_KEY,
    DISMISSED_NOTIFICATIONS_TTL_MS,
  ),
};

export const FINAL_JOB_STATUSES: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'cancelled',
  'lost',
]);

const JOB_STATUSES: ReadonlySet<string> = new Set([
  'working',
  ...FINAL_JOB_STATUSES,
]);

type JobUpdatedPayload = {
  job_id?: string;
  conversation_id?: string | null;
  status?: string;
  progress?: BackgroundJobProgress;
  tool_name?: string;
  action_name?: string;
};

function mergeJob(
  state: BackgroundState,
  update: Partial<BackgroundJobSummary> & { job_id: string },
) {
  const existing = state.jobs[update.job_id];
  const status = (
    update.status && JOB_STATUSES.has(update.status)
      ? update.status
      : (existing?.status ?? 'working')
  ) as BackgroundJobStatus;
  // A final state never goes back to running: a late event or a slow fetch
  // that read the row before it finished must not revive the card.
  if (
    existing &&
    FINAL_JOB_STATUSES.has(existing.status) &&
    status === 'working'
  ) {
    return;
  }
  // A partial update (an event without the start time) keeps what is known.
  const known = Object.fromEntries(
    Object.entries(update).filter(([, value]) => value !== undefined),
  );
  state.jobs[update.job_id] = {
    ...existing,
    ...known,
    job_id: update.job_id,
    status,
    receivedAt: Date.now(),
  };
}

function syncUnread(state: BackgroundState, list: ConversationSummary[]) {
  for (const chat of list) {
    if (chat.unread) state.unread[chat.id] = true;
    else if (chat.unread === false) delete state.unread[chat.id];
  }
}

export const fetchBackgroundJob = createAsyncThunk<
  BackgroundJobSummary,
  string,
  { state: { preference: { token: string | null } } }
>('background/fetchJob', async (jobId, { getState }) =>
  backgroundService.getJob(jobId, getState().preference.token),
);

/** The fewest milliseconds between two job-list fetches of one conversation. */
export const JOB_LIST_MIN_INTERVAL_MS = 5_000;

/**
 * Refresh every job of a conversation in one request: the cards' fallback
 * while the event stream is down. Several cards asking at once share it.
 */
export const fetchConversationJobs = createAsyncThunk<
  BackgroundJobSummary[],
  string,
  {
    state: {
      preference: { token: string | null };
      background?: BackgroundState;
    };
  }
>(
  'background/fetchConversationJobs',
  async (conversationId, { getState }) =>
    backgroundService.listJobs(conversationId, getState().preference.token),
  {
    condition: (conversationId, { getState }) => {
      const last = getState().background?.jobListRequestedAt[conversationId];
      return (
        last === undefined || Date.now() - last >= JOB_LIST_MIN_INTERVAL_MS
      );
    },
  },
);

// A job the server won't show this user: stop asking.
const NOT_READABLE = /^HTTP (401|403|404)$/;

export const cancelBackgroundJob = createAsyncThunk<
  BackgroundJobSummary,
  string,
  { state: { preference: { token: string | null } } }
>('background/cancelJob', async (jobId, { getState }) =>
  backgroundService.cancelJob(jobId, getState().preference.token),
);

export const fetchPushConfig = createAsyncThunk<
  PushConfig,
  void,
  { state: { preference: { token: string | null } } }
>('background/fetchPushConfig', async (_, { getState }) =>
  backgroundService.getPushConfig(getState().preference.token),
);

/** Clear a conversation's unread mark here at once, and on the server. */
export const markConversationRead = createAsyncThunk<
  void,
  string,
  { state: { preference: { token: string | null } } }
>('background/markRead', async (conversationId, { getState }) =>
  backgroundService.markConversationRead(
    conversationId,
    getState().preference.token,
  ),
);

export const backgroundSlice = createSlice({
  name: 'background',
  initialState,
  reducers: {
    markConversationUnread(state, action: PayloadAction<string>) {
      state.unread[action.payload] = true;
    },
    /** Show the Web Push prompt; a feature that started background work dispatches it. */
    requestPushPrompt(state) {
      state.pushPromptOpen = true;
    },
    closePushPrompt(state) {
      state.pushPromptOpen = false;
    },
    dismissConversationNotification(state, action: PayloadAction<string>) {
      const now = Date.now();
      const cutoff = now - DISMISSED_NOTIFICATIONS_TTL_MS;
      state.dismissedNotifications = state.dismissedNotifications
        .filter((entry) => entry.at >= cutoff && entry.id !== action.payload)
        .concat({ id: action.payload, at: now })
        .slice(-DISMISSED_NOTIFICATIONS_CAP);
      saveDismissed(
        DISMISSED_NOTIFICATIONS_STORAGE_KEY,
        state.dismissedNotifications,
      );
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(sseEventReceived, (state, action: PayloadAction<SSEEvent>) => {
        if (action.payload.type !== 'job.updated') return;
        const payload = (action.payload.payload ?? {}) as JobUpdatedPayload;
        if (!payload.job_id) return;
        mergeJob(state, {
          job_id: payload.job_id,
          conversation_id: payload.conversation_id,
          status: payload.status as BackgroundJobStatus,
          progress: payload.progress,
          tool_name: payload.tool_name,
          action_name: payload.action_name,
        });
      })
      .addCase(fetchBackgroundJob.fulfilled, (state, action) => {
        mergeJob(state, action.payload);
      })
      .addCase(fetchBackgroundJob.rejected, (state, action) => {
        if (NOT_READABLE.test(action.error.message ?? '')) {
          state.unavailableJobs[action.meta.arg] = true;
        }
      })
      .addCase(fetchConversationJobs.pending, (state, action) => {
        state.jobListRequestedAt[action.meta.arg] = Date.now();
      })
      .addCase(fetchConversationJobs.fulfilled, (state, action) => {
        for (const job of action.payload) {
          if (job?.job_id) mergeJob(state, job);
        }
      })
      .addCase(cancelBackgroundJob.fulfilled, (state, action) => {
        mergeJob(state, action.payload);
      })
      .addCase(fetchPushConfig.fulfilled, (state, action) => {
        state.pushConfig = action.payload;
      })
      .addCase(fetchPushConfig.rejected, (state) => {
        state.pushConfig = { enabled: false, public_key: null };
      })
      .addCase(markConversationRead.pending, (state, action) => {
        delete state.unread[action.meta.arg];
      })
      .addCase(receiveConversations, (state, action) => {
        if (action.payload.data) syncUnread(state, action.payload.data);
      })
      .addCase(appendConversations, (state, action) => {
        syncUnread(state, action.payload);
      });
  },
});

export const {
  markConversationUnread,
  requestPushPrompt,
  closePushPrompt,
  dismissConversationNotification,
} = backgroundSlice.actions;

// Optional: a store built without this slice (a component test) reads as empty.
type WithBackground = { background?: BackgroundState };

const NO_UNREAD: Record<string, true> = {};
const NO_DISMISSED: DismissedEntry[] = [];

export const selectBackgroundJob =
  (jobId: string | undefined) =>
  (state: WithBackground): BackgroundJob | undefined =>
    jobId ? state.background?.jobs[jobId] : undefined;

export const selectJobUnavailable =
  (jobId: string | undefined) =>
  (state: WithBackground): boolean =>
    Boolean(jobId && state.background?.unavailableJobs[jobId]);

export const selectIsUnread =
  (conversationId: string) =>
  (state: WithBackground): boolean =>
    Boolean(state.background?.unread[conversationId]);

export const selectUnread = (state: WithBackground) =>
  state.background?.unread ?? NO_UNREAD;

export const selectPushConfig = (state: WithBackground) =>
  state.background?.pushConfig ?? null;

export const selectPushPromptOpen = (state: WithBackground) =>
  Boolean(state.background?.pushPromptOpen);

export const selectDismissedNotifications = (state: WithBackground) =>
  state.background?.dismissedNotifications ?? NO_DISMISSED;

export default backgroundSlice.reducer;
