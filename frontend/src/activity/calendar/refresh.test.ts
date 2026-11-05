import { describe, expect, it } from 'vitest';

import { MISSED_GRACE_MS, MIN_REFRESH_MS, nextRefreshAt } from './refresh';
import type { CalendarEvent, ScheduleEvent } from './types';

const NOW = Date.parse('2026-10-15T12:00:00Z');
const MINUTE = 60_000;

const slot = (overrides: Partial<ScheduleEvent>): CalendarEvent => ({
  kind: 'schedule',
  schedule_id: 's1',
  name: 'Digest',
  agent_id: null,
  agent_name: null,
  trigger_type: 'recurring',
  cron: '0 * * * *',
  timezone: 'UTC',
  origin_conversation_id: null,
  origin_conversation_name: null,
  frequent: false,
  at: new Date(NOW + 30 * MINUTE).toISOString(),
  state: 'planned',
  ...overrides,
});

const iso = (offset: number) => new Date(NOW + offset).toISOString();

describe('nextRefreshAt', () => {
  it('is when the first planned slot would turn missed', () => {
    const events = [
      slot({ at: iso(90 * MINUTE) }),
      slot({ at: iso(30 * MINUTE) }),
    ];
    expect(nextRefreshAt(events, NOW)).toBe(
      NOW + 30 * MINUTE + MISSED_GRACE_MS,
    );
  });

  it('counts a slot already past but still inside the grace period', () => {
    const events = [slot({ at: iso(-4 * MINUTE) })];
    expect(nextRefreshAt(events, NOW)).toBe(NOW - 4 * MINUTE + MISSED_GRACE_MS);
  });

  it('waits at least a minute when the server still calls a late slot planned', () => {
    const events = [slot({ at: iso(-30 * MINUTE) })];
    expect(nextRefreshAt(events, NOW)).toBe(NOW + MIN_REFRESH_MS);
  });

  it('keeps refreshing through a summed-up day that is under way', () => {
    const events = [
      slot({
        frequent: true,
        count: 96,
        at: iso(-6 * 60 * MINUTE),
        until: iso(6 * 60 * MINUTE),
      }),
    ];
    const due = nextRefreshAt(events, NOW)!;
    expect(due).toBeGreaterThan(NOW);
    expect(due).toBeLessThanOrEqual(NOW + 5 * MINUTE);
  });

  it('ignores runs, missed slots, paused slots and syncs', () => {
    const events: CalendarEvent[] = [
      slot({ state: 'success', run_id: 'r1' }),
      slot({ state: 'missed', at: iso(-60 * MINUTE) }),
      slot({ state: 'paused' }),
      {
        kind: 'sync',
        schedule_id: 'sync:daily',
        name: null,
        agent_id: null,
        agent_name: null,
        frequent: false,
        at: iso(30 * MINUTE),
        state: 'planned',
        frequency: 'daily',
        sources: [],
      },
    ];
    expect(nextRefreshAt(events, NOW)).toBeNull();
  });
});
