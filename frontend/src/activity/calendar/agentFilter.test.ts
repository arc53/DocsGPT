import { describe, expect, it } from 'vitest';

import { agentOptions } from './agentFilter';
import type { CalendarEvent } from './types';

const slot = (agent_id: string | null, agent_name: string | null) =>
  ({
    kind: 'schedule',
    schedule_id: `s-${agent_id}`,
    name: 'x',
    agent_id,
    agent_name,
    frequent: false,
    at: '2026-10-15T09:00:00Z',
    state: 'planned',
  }) as CalendarEvent;

describe('agentOptions', () => {
  it('lists the agents with a slot in the window, by name, and chat tasks', () => {
    const options = agentOptions(
      [slot('a2', 'Zed'), slot('a1', 'Ada'), slot(null, null)],
      null,
    );
    expect(options.list).toEqual([
      ['a1', 'Ada'],
      ['a2', 'Zed'],
    ]);
    expect(options.chat).toBe(true);
  });

  it('keeps the chosen agent listed in a window it has no slot in', () => {
    // Else the filter reads blank while it still hides every other slot.
    const options = agentOptions([slot('a2', 'Zed')], {
      id: 'a1',
      name: 'Ada',
    });
    expect(options.list).toEqual([
      ['a1', 'Ada'],
      ['a2', 'Zed'],
    ]);
  });

  it('keeps chat tasks listed when they are the choice', () => {
    expect(agentOptions([slot('a2', 'Zed')], 'chat').chat).toBe(true);
    expect(agentOptions([slot('a2', 'Zed')], null).chat).toBe(false);
  });
});
