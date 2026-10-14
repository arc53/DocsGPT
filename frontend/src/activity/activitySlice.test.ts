import { describe, expect, it, vi } from 'vitest';

vi.mock('../api/services/activityService', () => ({
  default: { now: vi.fn(), stopMessage: vi.fn() },
}));

import { markConversationRead } from '../backgroundJobs/backgroundSlice';
import {
  sseEventReceived,
  type SSEEvent,
} from '../notifications/notificationsSlice';
import reducer, {
  loadActivityNow,
  selectActivityRevision,
  selectApprovalConversations,
  selectFailedConversations,
  selectWorkingConversations,
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
  stats: { running: 3, needs_you: 0, next_24h: 0, failed_24h: 0 },
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

  describe('revision', () => {
    // Calendar, Logs and History reload when it moves, so it moves only
    // when their data may have changed.
    const fetched = (
      state: ActivityState,
      now: NowSnapshot,
      reason?: 'event' | 'poll',
    ) => reducer(state, loadActivityNow.fulfilled(now, 'req', reason));
    const revision = (state: ActivityState) =>
      selectActivityRevision(wrap(state));
    const polled = () =>
      fetched(reducer(undefined, { type: '@@init' }), snapshot(), 'poll');

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

  it('reads as empty in a store without the slice', () => {
    expect(selectWorkingConversations({}).size).toBe(0);
    expect(selectApprovalConversations({}).size).toBe(0);
  });
});
