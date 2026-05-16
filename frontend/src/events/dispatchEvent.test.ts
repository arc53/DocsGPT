import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { AppDispatch } from '../store';
import {
  sseEventReceived,
  sseLastEventIdReset,
} from '../notifications/notificationsSlice';
import { dispatchSSEEvent } from './dispatchEvent';

describe('dispatchSSEEvent', () => {
  let debugSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    debugSpy = vi.spyOn(console, 'debug').mockImplementation(() => undefined);
  });

  afterEach(() => {
    debugSpy.mockRestore();
  });

  it('dispatches sseLastEventIdReset AND sseEventReceived for backlog.truncated', () => {
    const dispatch = vi.fn() as unknown as AppDispatch;
    const envelope = { type: 'backlog.truncated' as const };

    dispatchSSEEvent(envelope, dispatch);

    const calls = (dispatch as unknown as { mock: { calls: unknown[][] } }).mock
      .calls;
    expect(calls).toHaveLength(2);
    expect(calls[0][0]).toEqual(sseLastEventIdReset());
    expect(calls[1][0]).toEqual(sseEventReceived(envelope));
  });

  it('does not log a debug line for known envelope types', () => {
    const dispatch = vi.fn() as unknown as AppDispatch;
    dispatchSSEEvent({ id: 'e-1', type: 'source.ingest.progress' }, dispatch);
    expect(debugSpy).not.toHaveBeenCalled();
  });

  it('logs a debug line for unknown envelope types', () => {
    const dispatch = vi.fn() as unknown as AppDispatch;
    dispatchSSEEvent({ id: 'e-2', type: 'mystery.event' }, dispatch);
    expect(debugSpy).toHaveBeenCalledTimes(1);
    expect(debugSpy.mock.calls[0]).toEqual([
      '[dispatchSSEEvent] unknown envelope type',
      'mystery.event',
    ]);
  });
});
