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

  it('reads as empty in a store without the slice', () => {
    expect(selectWorkingConversations({}).size).toBe(0);
    expect(selectApprovalConversations({}).size).toBe(0);
  });
});
