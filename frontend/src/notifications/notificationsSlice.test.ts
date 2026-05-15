import { describe, expect, it, vi, afterEach } from 'vitest';

import reducer, {
  dismissToolApproval,
  sseEventReceived,
  sseLastEventIdReset,
  type SSEEvent,
} from './notificationsSlice';

const baseEvent = (overrides: Partial<SSEEvent> = {}): SSEEvent => ({
  id: 'evt-1',
  type: 'source.ingest.progress',
  ...overrides,
});

const seedState = () => reducer(undefined, { type: '@@INIT' });

afterEach(() => {
  vi.useRealTimers();
});

describe('sseEventReceived', () => {
  it('dedupes by id when the same envelope arrives twice', () => {
    let state = seedState();
    state = reducer(state, sseEventReceived(baseEvent({ id: 'a' })));
    state = reducer(state, sseEventReceived(baseEvent({ id: 'a' })));
    expect(state.recentEvents).toHaveLength(1);
    expect(state.recentEvents[0].id).toBe('a');
  });

  it('does not update lastEventId for envelopes without an id (backlog.truncated)', () => {
    let state = seedState();
    state = reducer(state, sseEventReceived(baseEvent({ id: 'cursor-1' })));
    expect(state.lastEventId).toBe('cursor-1');
    state = reducer(
      state,
      sseEventReceived({ type: 'backlog.truncated' } as SSEEvent),
    );
    expect(state.lastEventId).toBe('cursor-1');
  });

  it('caps recentEvents at 100 entries (oldest evicted)', () => {
    let state = seedState();
    for (let i = 0; i < 105; i += 1) {
      state = reducer(state, sseEventReceived(baseEvent({ id: `e-${i}` })));
    }
    expect(state.recentEvents).toHaveLength(100);
    // Newest first.
    expect(state.recentEvents[0].id).toBe('e-104');
    expect(state.recentEvents[state.recentEvents.length - 1].id).toBe('e-5');
  });
});

describe('sseLastEventIdReset', () => {
  it('clears lastEventId back to null', () => {
    let state = seedState();
    state = reducer(state, sseEventReceived(baseEvent({ id: 'x' })));
    expect(state.lastEventId).toBe('x');
    state = reducer(state, sseLastEventIdReset());
    expect(state.lastEventId).toBeNull();
  });
});

describe('dismissToolApproval', () => {
  it('dedupes by id and refreshes the timestamp', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    let state = seedState();
    state = reducer(state, dismissToolApproval('approval-1'));
    const firstAt = state.dismissedToolApprovals[0].at;

    vi.setSystemTime(new Date('2026-01-01T00:05:00Z'));
    state = reducer(state, dismissToolApproval('approval-1'));
    expect(state.dismissedToolApprovals).toHaveLength(1);
    expect(state.dismissedToolApprovals[0].at).toBeGreaterThan(firstAt);
  });

  it('evicts entries older than the 24h TTL', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    let state = seedState();
    state = reducer(state, dismissToolApproval('old-1'));

    // Move past the 24h TTL window.
    vi.setSystemTime(new Date('2026-01-02T00:00:01Z'));
    state = reducer(state, dismissToolApproval('fresh-1'));
    const ids = state.dismissedToolApprovals.map((entry) => entry.id);
    expect(ids).toEqual(['fresh-1']);
  });

  it('applies the 200-entry cap as a backstop after TTL filtering', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-01T00:00:00Z'));
    let state = seedState();
    // Insert 205 distinct ids within the TTL window.
    for (let i = 0; i < 205; i += 1) {
      // Advance time slightly so the at-values are distinct but well
      // inside the 24h TTL.
      vi.setSystemTime(
        new Date(`2026-01-01T00:00:${(i % 60).toString().padStart(2, '0')}Z`),
      );
      state = reducer(state, dismissToolApproval(`id-${i}`));
    }
    expect(state.dismissedToolApprovals).toHaveLength(200);
    // The 200-cap keeps the most recently pushed ids.
    expect(state.dismissedToolApprovals[0].id).toBe('id-5');
    expect(state.dismissedToolApprovals[199].id).toBe('id-204');
  });
});
