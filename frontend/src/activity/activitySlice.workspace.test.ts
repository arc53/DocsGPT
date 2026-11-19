import { configureStore } from '@reduxjs/toolkit';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/services/activityService', () => ({
  default: { now: vi.fn(), stopMessage: vi.fn() },
}));

import activityService from '../api/services/activityService';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import { switchWorkspace } from '../workspace/workspaceSlice';
import reducer, {
  activityListenerMiddleware,
  REFRESH_DEBOUNCE_MS,
  resetActivity,
  selectLiveConversations,
} from './activitySlice';
import type { NowSnapshot } from './types';

const snapshot = (): NowSnapshot => ({
  running: [],
  needs_you: [],
  up_next: [],
  approval_conversations: [],
  failed_conversations: [],
  stats: { next_24h: 0, failed_24h: 0 },
});

const event = (type: string, payload: Record<string, unknown>): SSEEvent =>
  ({ id: 'e', type, payload }) as SSEEvent;

const inWorkspace = (id: string) => reducer(undefined, switchWorkspace(id));

afterEach(() => vi.useRealTimers());

describe('activity and the workspace', () => {
  it("ignores a chat that started in another team's workspace", () => {
    const state = reducer(
      inWorkspace('t1'),
      sseEventReceived(
        event('message.started', { conversation_id: 'c1', team_id: 't2' }),
      ),
    );
    expect(selectLiveConversations({ activity: state })).toEqual({});
  });

  it('ignores a team event while in Personal', () => {
    const state = reducer(
      inWorkspace('personal'),
      sseEventReceived(
        event('message.started', { conversation_id: 'c1', team_id: 't2' }),
      ),
    );
    expect(selectLiveConversations({ activity: state })).toEqual({});
  });

  it('takes an event of the current team, and a Personal one in Personal', () => {
    let state = reducer(
      inWorkspace('t1'),
      sseEventReceived(
        event('message.started', { conversation_id: 'c1', team_id: 't1' }),
      ),
    );
    expect(selectLiveConversations({ activity: state })).toEqual({ c1: true });
    state = reducer(
      inWorkspace('personal'),
      sseEventReceived(
        event('message.started', { conversation_id: 'c2', team_id: null }),
      ),
    );
    expect(selectLiveConversations({ activity: state })).toEqual({ c2: true });
  });

  it("takes an event that doesn't say its workspace", () => {
    const state = reducer(
      inWorkspace('t1'),
      sseEventReceived(event('message.started', { conversation_id: 'c3' })),
    );
    expect(selectLiveConversations({ activity: state })).toEqual({ c3: true });
  });

  it('remembers the workspace through a sign-in reset', () => {
    const state = reducer(inWorkspace('t1'), resetActivity());
    expect(state.workspace).toBe('t1');
  });

  it("doesn't refetch for another workspace's event", async () => {
    vi.useFakeTimers();
    vi.mocked(activityService.now).mockReset();
    vi.mocked(activityService.now).mockResolvedValue(snapshot());
    const store = configureStore({
      reducer: {
        activity: reducer,
        preference: () => ({ token: null as string | null }),
      },
      middleware: (getDefault) =>
        getDefault().prepend(activityListenerMiddleware.middleware),
    });
    store.dispatch(switchWorkspace('t1'));
    store.dispatch(
      sseEventReceived(
        event('source.ingest.queued', { source_id: 's1', team_id: 't2' }),
      ),
    );
    await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS + 10);
    expect(activityService.now).not.toHaveBeenCalled();

    store.dispatch(
      sseEventReceived(
        event('source.ingest.queued', { source_id: 's1', team_id: 't1' }),
      ),
    );
    await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS + 10);
    expect(activityService.now).toHaveBeenCalledTimes(1);
  });
});
