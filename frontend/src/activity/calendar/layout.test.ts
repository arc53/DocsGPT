import { describe, expect, it } from 'vitest';

import {
  blockCount,
  blockState,
  eventClass,
  hourRange,
  layoutDay,
  STATE_CLASS,
  SYNC_CLASS,
} from './layout';
import type { ScheduleEvent, SyncEvent } from './types';

const event = (
  hour: number,
  overrides: Partial<ScheduleEvent> = {},
): ScheduleEvent => ({
  kind: 'schedule',
  schedule_id: 's1',
  name: 'Digest',
  agent_id: null,
  agent_name: null,
  trigger_type: 'recurring',
  cron: null,
  timezone: null,
  origin_conversation_id: null,
  origin_conversation_name: null,
  frequent: false,
  at: new Date(2026, 9, 13, Math.floor(hour), (hour % 1) * 60).toISOString(),
  state: 'planned',
  ...overrides,
});

describe('layoutDay', () => {
  it('counts a summed-up day by its runs and spans it to its last', () => {
    const { blocks } = layoutDay([
      event(0, {
        frequent: true,
        state: 'success',
        count: 10,
        until: event(9).at,
      }),
      event(10, { frequent: true, state: 'failed' }),
    ]);
    expect(blockCount(blocks[0])).toBe(11);
    expect([blocks[0].from, blocks[0].to]).toEqual([0, 10]);
    const {
      blocks: [only],
    } = layoutDay([
      event(0, { frequent: true, count: 24, until: event(23).at }),
    ]);
    expect(only.to).toBe(23);
  });

  it('fits a summed-up day into the hours shown', () => {
    expect(hourRange([event(8, { count: 3, until: event(21).at })])[1]).toBe(
      22,
    );
  });

  it('puts overlapping slots side by side and lone ones full width', () => {
    const { placed } = layoutDay([
      event(8, { schedule_id: 'a' }),
      event(8, { schedule_id: 'b' }),
      event(15, { schedule_id: 'c' }),
    ]);
    const byId = Object.fromEntries(
      placed.map((p) => [p.event.schedule_id, p]),
    );
    expect([byId.a.lane, byId.b.lane]).toEqual([0, 1]);
    expect(byId.a.lanes).toBe(2);
    expect(byId.c).toMatchObject({ lane: 0, lanes: 1 });
  });

  it('collapses a frequent schedule into one block from its first to its last run', () => {
    const runs = [8, 9, 10, 11].map((h) =>
      event(h, { schedule_id: 'hourly', frequent: true }),
    );
    const { placed, blocks } = layoutDay(runs);
    expect(placed).toEqual([]);
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toMatchObject({ from: 8, to: 11 });
    expect(blocks[0].events).toHaveLength(4);
  });
});

describe('blockState', () => {
  it('shows the worst state of the day', () => {
    expect(
      blockState([
        event(8, { state: 'success' }),
        event(9, { state: 'failed' }),
      ]),
    ).toBe('failed');
    expect(blockState([event(8, { state: 'success' }), event(9)])).toBe(
      'planned',
    );
  });
});

describe('hourRange', () => {
  it('shows working hours by default and widens to fit', () => {
    expect(hourRange([])).toEqual([7, 19]);
    expect(hourRange([event(6), event(21.5)])).toEqual([6, 22]);
  });
});

describe('sync events', () => {
  const sync: SyncEvent = {
    kind: 'sync',
    schedule_id: 'sync:daily',
    name: null,
    agent_id: null,
    agent_name: null,
    frequent: false,
    at: new Date(2026, 9, 13, 3, 12).toISOString(),
    state: 'planned',
    frequency: 'daily',
    sources: [],
  };

  it('have their own look, not a run status', () => {
    expect(eventClass(sync)).toBe(SYNC_CLASS);
    expect(eventClass(event(8))).toBe(STATE_CLASS.planned);
  });

  it('are slots, and widen the day to their time', () => {
    const { placed, blocks } = layoutDay([sync, event(15)]);
    expect(placed.map((p) => p.event.kind)).toEqual(['sync', 'schedule']);
    expect(blocks).toEqual([]);
    expect(hourRange([sync])[0]).toBe(3);
  });
});
