import {
  createAsyncThunk,
  createListenerMiddleware,
  createSelector,
  createSlice,
  type PayloadAction,
} from '@reduxjs/toolkit';

import activityService from '../api/services/activityService';
import { markConversationRead } from '../backgroundJobs/backgroundSlice';
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
};

const initialState: ActivityState = {
  now: null,
  loading: false,
  error: false,
  live: {},
};

export const loadActivityNow = createAsyncThunk<
  NowSnapshot,
  void,
  { state: { preference: { token: string | null } } }
>('activity/loadNow', async (_, { getState }) =>
  activityService.now(getState().preference.token),
);

const activitySlice = createSlice({
  name: 'activity',
  initialState,
  reducers: {
    resetActivity: () => initialState,
  },
  extraReducers: (builder) => {
    builder
      .addCase(loadActivityNow.pending, (state) => {
        state.loading = true;
      })
      .addCase(loadActivityNow.fulfilled, (state, action) => {
        state.now = action.payload;
        state.loading = false;
        state.error = false;
        state.live = {};
      })
      .addCase(loadActivityNow.rejected, (state) => {
        state.loading = false;
        state.error = true;
      })
      // Opening a chat clears its unread mark, and with it the failed mark.
      .addCase(markConversationRead.pending, (state, action) => {
        if (!state.now) return;
        state.now.failed_conversations = state.now.failed_conversations.filter(
          (id) => id !== action.meta.arg,
        );
      })
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

/** Refetches wait this long so a burst of events costs one request. */
export const REFRESH_DEBOUNCE_MS = 800;

/** Refetches the snapshot after the events that change it, debounced. */
export const activityListenerMiddleware = createListenerMiddleware();

activityListenerMiddleware.startListening({
  predicate: (action) =>
    action.type === sseEventReceived.type &&
    REFRESH_EVENTS.has((action as PayloadAction<SSEEvent>).payload?.type),
  effect: async (_action, api) => {
    api.cancelActiveListeners();
    await api.delay(REFRESH_DEBOUNCE_MS);
    await api.dispatch(loadActivityNow() as never);
  },
});

type WithActivity = { activity?: ActivityState };

export const selectActivityNow = (state: WithActivity) =>
  state.activity?.now ?? null;
export const selectActivityLoading = (state: WithActivity) =>
  state.activity?.loading ?? false;
export const selectActivityError = (state: WithActivity) =>
  state.activity?.error ?? false;

const NO_LIVE: Record<string, true> = {};
/** Chats whose answer started after the last snapshot. */
export const selectLiveConversations = (state: WithActivity) =>
  state.activity?.live ?? NO_LIVE;

const EMPTY: ReadonlySet<string> = new Set();

/** Chats answering or running a background job. */
export const selectWorkingConversations = createSelector(
  [selectActivityNow, selectLiveConversations],
  (now, live): ReadonlySet<string> => {
    const ids = new Set(Object.keys(live));
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
