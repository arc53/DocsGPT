import {
  createAsyncThunk,
  createListenerMiddleware,
  createSelector,
  createSlice,
  isAnyOf,
  type PayloadAction,
} from '@reduxjs/toolkit';

import activityService from '../api/services/activityService';
import { markConversationRead } from '../backgroundJobs/backgroundSlice';
import {
  removeAllConversations,
  removeConversation,
} from '../preferences/preferenceSlice';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import type { NowSnapshot } from './types';

export type ActivityState = {
  now: NowSnapshot | null;
  loading: boolean;
  error: boolean;
  /**
   * Chats an answer started in since the last snapshot (`message.started`),
   * so the sidebar spins at once instead of after the refetch.
   */
  live: Record<string, true>;
  /**
   * Moves when what Calendar, Logs and History show may have changed: after
   * an event that ended something, or a fetch that finds something left
   * Running or a change outside it. Something new running, a step moving and
   * local patches leave it, so those pages don't reload for every start.
   */
  revision: number;
  /** The last fetched snapshot without `running`, serialized. */
  settled: string | null;
  /**
   * The latest fetch's id. The poll, event refetches and Retry overlap, so
   * only its answer is applied: an older one would put back what changed.
   */
  requestId: string | null;
  /** Chats in `live` when the latest fetch went out; its answer covers them. */
  liveAtRequest: string[];
  /** Chats whose answer finished after the latest fetch went out. */
  finishedSinceRequest: string[];
  /**
   * Chats opened whose read the server may not have stored when the latest
   * fetch went out (opened since, or still being marked read then); it may
   * still call them failed.
   */
  readSinceRequest: string[];
  /** Chats being marked read, until the server answers. */
  readPending: string[];
};

const initialState: ActivityState = {
  now: null,
  loading: false,
  error: false,
  live: {},
  revision: 0,
  settled: null,
  requestId: null,
  liveAtRequest: [],
  finishedSinceRequest: [],
  readSinceRequest: [],
  readPending: [],
};

/** Whether a fetch's answer is the latest one's (or none is being tracked). */
const isLatest = (state: ActivityState, requestId: string) =>
  state.requestId === null || state.requestId === requestId;

/**
 * Why a refetch runs: `event` after live events one of which ended something,
 * `progress` after ones that only started or moved something, `poll` for the
 * slow refresh. Without one it counts as a poll.
 */
export type ActivityRefresh = 'event' | 'progress' | 'poll';

/** The snapshot without what is running, which the other pages don't show. */
const settledKey = (now: NowSnapshot) =>
  JSON.stringify({ ...now, running: undefined });

export const loadActivityNow = createAsyncThunk<
  NowSnapshot,
  ActivityRefresh | void,
  { state: { preference: { token: string | null } } }
>('activity/loadNow', async (_reason, { getState }) =>
  activityService.now(getState().preference.token),
);

const activitySlice = createSlice({
  name: 'activity',
  initialState,
  reducers: {
    // Another account: its fetch comes next, and an answer to one sent
    // before (no request id matches this) is the last account's.
    resetActivity: () => ({ ...initialState, requestId: 'reset' }),
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadActivityNow.pending, (state, action) => {
        state.loading = true;
        state.requestId = action.meta.requestId;
        state.liveAtRequest = Object.keys(state.live);
        state.finishedSinceRequest = [];
        state.readSinceRequest = [...state.readPending];
      })
      .addCase(loadActivityNow.fulfilled, (state, action) => {
        if (!isLatest(state, action.meta.requestId)) return;
        // An ending event says something happened even when the snapshot
        // reads the same: a run can start and end between two fetches.
        const settled = settledKey(action.payload);
        const fresh = new Set(action.payload.running.map((item) => item.id));
        const ended = (state.now?.running ?? []).some(
          (item) => !fresh.has(item.id),
        );
        // The first snapshot is no news: a page opened first loaded already.
        const changed = state.settled !== null && settled !== state.settled;
        if (action.meta.arg === 'event' || ended || changed) {
          state.revision += 1;
        }
        state.settled = settled;
        // The server may have read before an answer that finished since,
        // or before a failed chat was opened.
        const finished = new Set(state.finishedSinceRequest);
        const read = new Set(state.readSinceRequest);
        state.now = {
          ...action.payload,
          running: finished.size
            ? action.payload.running.filter(
                (item) =>
                  !(
                    item.kind === 'chat' &&
                    item.conversation_id &&
                    finished.has(item.conversation_id)
                  ),
              )
            : action.payload.running,
          failed_conversations: read.size
            ? action.payload.failed_conversations.filter((id) => !read.has(id))
            : action.payload.failed_conversations,
        };
        state.loading = false;
        state.error = false;
        // Answers that started after the fetch went out stay live.
        for (const id of state.liveAtRequest) delete state.live[id];
        state.liveAtRequest = [];
        state.finishedSinceRequest = [];
        state.readSinceRequest = [];
      })
      .addCase(loadActivityNow.rejected, (state, action) => {
        if (!isLatest(state, action.meta.requestId)) return;
        state.loading = false;
        state.error = true;
      })
      // Opening a chat clears its unread mark, and with it the failed mark.
      .addCase(markConversationRead.pending, (state, action) => {
        state.readPending.push(action.meta.arg);
        if (state.loading) state.readSinceRequest.push(action.meta.arg);
        if (!state.now) return;
        state.now.failed_conversations = state.now.failed_conversations.filter(
          (id) => id !== action.meta.arg,
        );
      })
      // A deleted chat has nothing to approve and no failure to read.
      .addCase(removeConversation, (state, action) => {
        if (!state.now) return;
        state.now.failed_conversations = state.now.failed_conversations.filter(
          (id) => id !== action.payload,
        );
        state.now.approval_conversations =
          state.now.approval_conversations.filter(
            (id) => id !== action.payload,
          );
      })
      .addCase(removeAllConversations, (state) => {
        if (!state.now) return;
        state.now.failed_conversations = [];
        state.now.approval_conversations = [];
      })
      .addMatcher(
        isAnyOf(markConversationRead.fulfilled, markConversationRead.rejected),
        (state, action) => {
          const at = state.readPending.indexOf(action.meta.arg);
          if (at !== -1) state.readPending.splice(at, 1);
        },
      )
      .addMatcher(
        (action) => action.type === sseEventReceived.type,
        (state, action: PayloadAction<SSEEvent>) => {
          const payload = (action.payload.payload || {}) as {
            conversation_id?: string;
          };
          const conversationId = payload.conversation_id;
          if (!conversationId) return;
          if (action.payload.type === 'message.started') {
            state.live[conversationId] = true;
          } else if (action.payload.type === 'message.finished') {
            delete state.live[conversationId];
            if (state.loading) state.finishedSinceRequest.push(conversationId);
            if (state.now) {
              state.now.running = state.now.running.filter(
                (item) =>
                  !(
                    item.kind === 'chat' &&
                    item.conversation_id === conversationId
                  ),
              );
            }
          }
        },
      );
  },
});

export const { resetActivity } = activitySlice.actions;
export default activitySlice.reducer;

/** Events after which the snapshot is out of date. */
const REFRESH_EVENTS: ReadonlySet<string> = new Set([
  'message.started',
  'message.finished',
  'job.updated',
  'conversation.continued',
  'schedule.run.started',
  'schedule.run.completed',
  'schedule.run.failed',
  'schedule.autopaused',
  'schedule.resumed',
  'schedule.cancelled',
  'schedule.completed',
  'activity.updated',
  'workflow.run.step',
  'tool.approval.required',
  'tool.approval.cleared',
  'source.ingest.queued',
  'source.ingest.completed',
  'source.ingest.failed',
]);

/** Events that start or move something, never end it. */
const PROGRESS_EVENTS: ReadonlySet<string> = new Set([
  'message.started',
  'workflow.run.step',
  'source.ingest.queued',
]);

const JOB_ENDED: ReadonlySet<string> = new Set([
  'completed',
  'failed',
  'cancelled',
  'lost',
]);

/** Whether an event may have added a row to Calendar, Logs or History. */
const endsSomething = (event: SSEEvent): boolean => {
  if (PROGRESS_EVENTS.has(event.type)) return false;
  const payload = (event.payload || {}) as {
    status?: string;
    running?: boolean;
  };
  if (event.type === 'job.updated') return JOB_ENDED.has(payload.status ?? '');
  // A webhook run's marker: `running` is false when it ends.
  if (event.type === 'activity.updated') return payload.running !== true;
  return true;
};

/** Refetches wait this long so a burst of events costs one request. */
export const REFRESH_DEBOUNCE_MS = 800;

/** Whether the burst the pending refetch waits out ended something. */
let burstEnded = false;

/** Refetches the snapshot after the events that change it, debounced. */
export const activityListenerMiddleware = createListenerMiddleware();

activityListenerMiddleware.startListening({
  predicate: (action) =>
    action.type === sseEventReceived.type &&
    REFRESH_EVENTS.has((action as PayloadAction<SSEEvent>).payload?.type),
  effect: async (action, api) => {
    if (endsSomething((action as PayloadAction<SSEEvent>).payload)) {
      burstEnded = true;
    }
    api.cancelActiveListeners();
    await api.delay(REFRESH_DEBOUNCE_MS);
    const reason: ActivityRefresh = burstEnded ? 'event' : 'progress';
    burstEnded = false;
    await api.dispatch(loadActivityNow(reason) as never);
  },
});

type WithActivity = { activity?: ActivityState };

export const selectActivityNow = (state: WithActivity) =>
  state.activity?.now ?? null;
export const selectActivityLoading = (state: WithActivity) =>
  state.activity?.loading ?? false;
export const selectActivityError = (state: WithActivity) =>
  state.activity?.error ?? false;
/** Follow this, not the snapshot, to reload when activity may have changed. */
export const selectActivityRevision = (state: WithActivity) =>
  state.activity?.revision ?? 0;

/**
 * What runs, as a key: it moves when a run starts or ends (or an API row's
 * request count changes), not when a run only moves a step. Logs follows it
 * to list runs as they start, which `revision` leaves alone.
 */
export const selectRunningKey = (state: WithActivity): string =>
  (state.activity?.now?.running ?? [])
    .map((item) => `${item.kind}:${item.id}:${item.count ?? 1}`)
    .sort()
    .join('|');

const NO_LIVE: Record<string, true> = {};
/** Chats whose answer started after the last snapshot. */
export const selectLiveConversations = (state: WithActivity) =>
  state.activity?.live ?? NO_LIVE;

const EMPTY: ReadonlySet<string> = new Set();

/** The chat this tab is streaming an answer into, if any. */
const selectStreamingConversation = (state: {
  conversation?: { conversationId: string | null; status: string };
}) =>
  state.conversation?.status === 'loading'
    ? state.conversation.conversationId
    : null;

/**
 * Chats answering or running a background job. The chat this tab streams
 * counts at once, with or without the event stream's `message.started`.
 */
export const selectWorkingConversations = createSelector(
  [selectActivityNow, selectLiveConversations, selectStreamingConversation],
  (now, live, streaming): ReadonlySet<string> => {
    const ids = new Set(Object.keys(live));
    if (streaming) ids.add(streaming);
    for (const item of now?.running ?? []) {
      if (
        (item.kind === 'chat' || item.kind === 'job') &&
        item.conversation_id
      ) {
        ids.add(item.conversation_id);
      }
    }
    return ids.size ? ids : EMPTY;
  },
);

/** Chats waiting for a tool approval. */
export const selectApprovalConversations = createSelector(
  [selectActivityNow],
  (now): ReadonlySet<string> =>
    now?.approval_conversations.length
      ? new Set(now.approval_conversations)
      : EMPTY,
);

/** Unread chats whose last answer or background job failed. */
export const selectFailedConversations = createSelector(
  [selectActivityNow],
  (now): ReadonlySet<string> =>
    now?.failed_conversations.length
      ? new Set(now.failed_conversations)
      : EMPTY,
);
