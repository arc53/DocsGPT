import { configureStore } from '@reduxjs/toolkit';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api/services/activityService', () => ({
  default: { now: vi.fn(), stopMessage: vi.fn() },
}));

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
import reducer, {
  activityListenerMiddleware,
  loadActivityNow,
  REFRESH_DEBOUNCE_MS,
  selectActivityRevision,
  selectApprovalConversations,
  selectFailedConversations,
  selectWorkingConversations,
  type ActivityRefresh,
  type ActivityState,
} from './activitySlice';
import type { NowSnapshot } from './types';

const snapshot = (overrides: Partial<NowSnapshot> = {}): NowSnapshot => ({
  running: [
    { kind: 'chat', id: 'm1', title: 'Chat', conversation_id: 'c1' },
    { kind: 'job', id: 'j1', title: 'QBR', conversation_id: 'c2' },
    { kind: 'schedule', id: 'r1', title: 'Digest' },
  ],
  needs_you: [],
  up_next: [],
  approval_conversations: ['c3'],
  failed_conversations: ['c4'],
  stats: { next_24h: 0, failed_24h: 0 },
  ...overrides,
});

const loaded = (): ActivityState =>
  reducer(undefined, loadActivityNow.fulfilled(snapshot(), 'req'));

const event = (type: string, conversationId: string): SSEEvent =>
  ({ id: 'e', type, payload: { conversation_id: conversationId } }) as SSEEvent;

const wrap = (activity: ActivityState) => ({ activity });

describe('activitySlice', () => {
  it('knows which chats work, wait for approval or failed', () => {
    const state = wrap(loaded());
    expect([...selectWorkingConversations(state)].sort()).toEqual(['c1', 'c2']);
    expect([...selectApprovalConversations(state)]).toEqual(['c3']);
    expect([...selectFailedConversations(state)]).toEqual(['c4']);
  });

  it('counts the chat this tab is streaming as working, event stream or not', () => {
    const streaming = {
      activity: loaded(),
      conversation: { conversationId: 'c8', status: 'loading' as const },
    };
    expect(selectWorkingConversations(streaming).has('c8')).toBe(true);
    const done = {
      ...streaming,
      conversation: { conversationId: 'c8', status: 'idle' as const },
    };
    expect(selectWorkingConversations(done).has('c8')).toBe(false);
  });

  it('marks a chat working as soon as its answer starts', () => {
    const state = reducer(
      loaded(),
      sseEventReceived(event('message.started', 'c9')),
    );
    expect(selectWorkingConversations(wrap(state)).has('c9')).toBe(true);
  });

  it('drops a chat when its answer finishes', () => {
    let state = reducer(
      loaded(),
      sseEventReceived(event('message.started', 'c9')),
    );
    state = reducer(state, sseEventReceived(event('message.finished', 'c9')));
    state = reducer(state, sseEventReceived(event('message.finished', 'c1')));
    const working = selectWorkingConversations(wrap(state));
    expect(working.has('c9')).toBe(false);
    expect(working.has('c1')).toBe(false);
    expect(working.has('c2')).toBe(true);
  });

  it('clears the failed mark when the chat is opened', () => {
    const state = reducer(loaded(), markConversationRead.pending('req', 'c4'));
    expect(selectFailedConversations(wrap(state)).size).toBe(0);
  });

  it('drops the failed and approval marks of a deleted chat', () => {
    let state = reducer(loaded(), removeConversation('c4'));
    expect(selectFailedConversations(wrap(state)).size).toBe(0);
    expect([...selectApprovalConversations(wrap(state))]).toEqual(['c3']);
    state = reducer(state, removeAllConversations());
    expect(selectApprovalConversations(wrap(state)).size).toBe(0);
  });

  describe('overlapping fetches', () => {
    // The poll, event refetches and Retry can overlap; responses can arrive
    // in any order.
    const working = (state: ActivityState) =>
      selectWorkingConversations(wrap(state));

    it('ignores a response older than the latest request', () => {
      let state = reducer(loaded(), loadActivityNow.pending('a', 'poll'));
      state = reducer(state, loadActivityNow.pending('b', 'event'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot({ running: [] }), 'b', 'event'),
      );
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'poll'),
      );
      expect(working(state).size).toBe(0);
      expect(state.loading).toBe(false);
    });

    it('stays loading until the latest request answers', () => {
      let state = reducer(loaded(), loadActivityNow.pending('a', 'poll'));
      state = reducer(state, loadActivityNow.pending('b', 'event'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'poll'),
      );
      expect(state.loading).toBe(true);
    });

    it('ignores an older request failing', () => {
      let state = reducer(loaded(), loadActivityNow.pending('a', 'poll'));
      state = reducer(state, loadActivityNow.pending('b', 'event'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'b', 'event'),
      );
      state = reducer(
        state,
        loadActivityNow.rejected(new Error('x'), 'a', 'poll'),
      );
      expect(state.error).toBe(false);
    });

    it('keeps a chat that started while the request was out', () => {
      let state = reducer(loaded(), loadActivityNow.pending('a', 'poll'));
      state = reducer(state, sseEventReceived(event('message.started', 'c9')));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'poll'),
      );
      expect(working(state).has('c9')).toBe(true);
    });

    it('drops a chat started before the request once it answers', () => {
      let state = reducer(
        loaded(),
        sseEventReceived(event('message.started', 'c9')),
      );
      state = reducer(state, loadActivityNow.pending('a', 'poll'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'poll'),
      );
      expect(working(state).has('c9')).toBe(false);
    });

    it('does not bring back a chat that finished while the request was out', () => {
      let state = reducer(loaded(), loadActivityNow.pending('a', 'poll'));
      state = reducer(state, sseEventReceived(event('message.finished', 'c1')));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'poll'),
      );
      expect(working(state).has('c1')).toBe(false);
      expect(working(state).has('c2')).toBe(true);
    });

    it('does not bring back the failed mark from a fetch sent before the read landed', () => {
      // Opened, then a fetch goes out while marking it read is still in
      // flight: the server may still read it unread.
      let state = reducer(loaded(), markConversationRead.pending('read', 'c4'));
      state = reducer(state, loadActivityNow.pending('b', 'event'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'b', 'event'),
      );
      expect(selectFailedConversations(wrap(state)).has('c4')).toBe(false);
      // Once the read is stored, a fetch sent after it is believed.
      state = reducer(
        state,
        markConversationRead.fulfilled(undefined as never, 'read', 'c4'),
      );
      state = reducer(state, loadActivityNow.pending('c', 'poll'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'c', 'poll'),
      );
      expect(selectFailedConversations(wrap(state)).has('c4')).toBe(true);
    });

    it('does not bring back the failed mark of a chat opened while the request was out', () => {
      // The server read the chat unread before it was opened.
      let state = reducer(loaded(), loadActivityNow.pending('a', 'event'));
      state = reducer(state, markConversationRead.pending('read', 'c4'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'a', 'event'),
      );
      expect(selectFailedConversations(wrap(state)).has('c4')).toBe(false);
      // The read is stored, and the next fetch read after it: whatever it
      // says stands.
      state = reducer(
        state,
        markConversationRead.fulfilled(undefined as never, 'read', 'c4'),
      );
      state = reducer(state, loadActivityNow.pending('b', 'poll'));
      state = reducer(
        state,
        loadActivityNow.fulfilled(snapshot(), 'b', 'poll'),
      );
      expect(selectFailedConversations(wrap(state)).has('c4')).toBe(true);
    });
  });

  describe('revision', () => {
    // Calendar, Logs and History reload when it moves, so it moves only
    // when their data may have changed.
    const fetched = (
      state: ActivityState,
      now: NowSnapshot,
      reason?: ActivityRefresh,
    ) => reducer(state, loadActivityNow.fulfilled(now, 'req', reason));
    const revision = (state: ActivityState) =>
      selectActivityRevision(wrap(state));
    const polled = () =>
      fetched(reducer(undefined, { type: '@@init' }), snapshot(), 'poll');

    it('stays put for the first snapshot, which is no news', () => {
      // A page opened first (History, Calendar) loaded already; moving
      // here would load it a second time.
      expect(revision(polled())).toBe(0);
    });

    it('stays put when a poll brings the same snapshot', () => {
      const first = polled();
      const again = fetched(first, snapshot(), 'poll');
      expect(revision(again)).toBe(revision(first));
    });

    it('moves when a poll brings a different one', () => {
      const first = polled();
      const next = fetched(first, snapshot({ running: [] }), 'poll');
      expect(revision(next)).toBe(revision(first) + 1);
    });

    it('moves after an event even when the snapshot reads the same', () => {
      // A run that started and ended between two fetches leaves no trace
      // in the snapshot, but History and Logs have a new row.
      const first = polled();
      const next = fetched(first, snapshot(), 'event');
      expect(revision(next)).toBe(revision(first) + 1);
    });

    it('stays put when only something new is running', () => {
      // An answer starting or a step moving adds nothing to Calendar, Logs
      // or History; they change when something ends.
      const first = polled();
      const started = snapshot({
        running: [
          ...snapshot().running,
          { kind: 'chat', id: 'm9', title: 'New', conversation_id: 'c9' },
        ],
        stats: { next_24h: 0, failed_24h: 0 },
      });
      expect(revision(fetched(first, started, 'progress'))).toBe(
        revision(first),
      );
      const moved = snapshot({
        running: snapshot().running.map((item) =>
          item.kind === 'job' ? { ...item, progress: 40 } : item,
        ),
      });
      expect(revision(fetched(first, moved, 'poll'))).toBe(revision(first));
    });

    it('moves when something left Running without an event', () => {
      const first = polled();
      const ended = snapshot({ running: snapshot().running.slice(1) });
      expect(revision(fetched(first, ended, 'progress'))).toBe(
        revision(first) + 1,
      );
    });

    it('moves when what waits or comes next changed', () => {
      const first = polled();
      const next = fetched(
        first,
        snapshot({ failed_conversations: [] }),
        'poll',
      );
      expect(revision(next)).toBe(revision(first) + 1);
    });

    it('stays put when the snapshot is patched locally', () => {
      const first = polled();
      let state = reducer(first, markConversationRead.pending('req', 'c4'));
      state = reducer(state, sseEventReceived(event('message.finished', 'c1')));
      expect(revision(state)).toBe(revision(first));
      // Nor does the patch make the next identical poll look new.
      expect(revision(fetched(state, snapshot(), 'poll'))).toBe(
        revision(first),
      );
    });
  });

  describe('refetch after events', () => {
    afterEach(() => {
      vi.useRealTimers();
      vi.mocked(activityService.now).mockReset();
    });

    const store = () =>
      configureStore({
        reducer: {
          activity: reducer,
          preference: () => ({ token: null as string | null }),
        },
        middleware: (getDefault) =>
          getDefault().prepend(activityListenerMiddleware.middleware),
      });

    const after = async (...events: SSEEvent[]) => {
      vi.useFakeTimers();
      vi.mocked(activityService.now).mockReset();
      vi.mocked(activityService.now).mockResolvedValue(snapshot());
      const s = store();
      s.dispatch(loadActivityNow.fulfilled(snapshot(), 'first', 'poll'));
      const before = s.getState().activity.revision;
      for (const e of events) s.dispatch(sseEventReceived(e));
      await vi.advanceTimersByTimeAsync(REFRESH_DEBOUNCE_MS + 10);
      expect(activityService.now).toHaveBeenCalledTimes(1);
      return s.getState().activity.revision - before;
    };
    const job = (status: string): SSEEvent =>
      ({
        id: 'e',
        type: 'job.updated',
        payload: { conversation_id: 'c2', status },
      }) as SSEEvent;

    it('leaves the other pages alone after a start or a step', async () => {
      expect(
        await after(
          event('message.started', 'c9'),
          event('workflow.run.step', 'c9'),
          job('running'),
        ),
      ).toBe(0);
    });

    it('reloads them when something in the burst ended', async () => {
      expect(
        await after(
          event('message.started', 'c9'),
          event('message.finished', 'c9'),
        ),
      ).toBe(1);
      expect(await after(job('completed'))).toBe(1);
    });
  });

  it('reads as empty in a store without the slice', () => {
    expect(selectWorkingConversations({}).size).toBe(0);
    expect(selectApprovalConversations({}).size).toBe(0);
  });
});
