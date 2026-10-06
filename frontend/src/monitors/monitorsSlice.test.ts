import { configureStore } from '@reduxjs/toolkit';
import { describe, expect, it, vi } from 'vitest';

const service = vi.hoisted(() => ({ list: vi.fn(), act: vi.fn() }));
vi.mock('../api/services/monitorsService', () => ({ default: service }));

import { sseEventReceived } from '../notifications/notificationsSlice';
import reducer, {
  actOnMonitor,
  loadMonitors,
  selectIsWatching,
  selectMonitors,
} from './monitorsSlice';
import { sampleMonitor } from './testing';

const store = () => configureStore({ reducer: { monitors: reducer } });

const updated = (payload: Record<string, unknown>) =>
  sseEventReceived({ type: 'monitor.updated', payload });

describe('monitorsSlice', () => {
  it('loads the list in order', async () => {
    service.list.mockResolvedValue([
      sampleMonitor({ monitor_id: 'b' }),
      sampleMonitor({ monitor_id: 'a' }),
    ]);
    const s = store();
    await s.dispatch(loadMonitors({ token: 't' }));
    expect(selectMonitors(s.getState()).map((m) => m.monitor_id)).toEqual([
      'b',
      'a',
    ]);
    expect(s.getState().monitors.loaded).toBe(true);
  });

  it('applies monitor.updated to a known monitor', async () => {
    service.list.mockResolvedValue([sampleMonitor()]);
    const s = store();
    await s.dispatch(loadMonitors({ token: 't' }));
    s.dispatch(
      updated({
        monitor_id: 'm-1',
        status: 'completed',
        wakes_left: 0,
        last_checked_at: '2026-10-05T13:00:00Z',
        conversation_id: 'c-1',
        check_count: 4,
      }),
    );
    const [monitor] = selectMonitors(s.getState());
    expect(monitor.status).toBe('completed');
    expect(monitor.wakes_left).toBe(0);
    expect(monitor.check_count).toBe(4);
    expect(monitor.description).toBe('ACMEB below $90');
  });

  it('learns about a new monitor from its event, so the chat shows it is watching', () => {
    const s = store();
    expect(selectIsWatching(s.getState(), 'c-9')).toBe(false);
    s.dispatch(
      updated({
        monitor_id: 'new',
        status: 'active',
        wakes_left: 1,
        last_checked_at: null,
        conversation_id: 'c-9',
      }),
    );
    expect(selectIsWatching(s.getState(), 'c-9')).toBe(true);
    s.dispatch(
      updated({
        monitor_id: 'new',
        status: 'cancelled',
        wakes_left: 1,
        last_checked_at: null,
        conversation_id: 'c-9',
      }),
    );
    expect(selectIsWatching(s.getState(), 'c-9')).toBe(false);
  });

  it('ignores other events and payloads without an id', () => {
    const s = store();
    s.dispatch(sseEventReceived({ type: 'job.updated', payload: {} }));
    s.dispatch(updated({ status: 'active' }));
    expect(selectMonitors(s.getState())).toEqual([]);
  });

  it('stores the monitor an action returns', async () => {
    service.act.mockResolvedValue(sampleMonitor({ status: 'paused' }));
    const s = store();
    await s.dispatch(actOnMonitor({ id: 'm-1', action: 'pause', token: 't' }));
    expect(service.act).toHaveBeenCalledWith('m-1', 'pause', 't');
    expect(selectMonitors(s.getState())[0].status).toBe('paused');
  });

  it('a store without the slice is not watching anything', () => {
    expect(selectIsWatching({}, 'c-1')).toBe(false);
    expect(selectMonitors({})).toEqual([]);
  });
});
