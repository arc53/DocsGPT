import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

const activity = vi.hoisted(() => ({
  now: vi.fn(),
  planned: vi.fn(),
  stopMessage: vi.fn(),
}));
vi.mock('../api/services/activityService', () => ({ default: activity }));
const schedules = vi.hoisted(() => ({ getRun: vi.fn(), runNow: vi.fn() }));
vi.mock('../api/services/schedulesService', () => ({ default: schedules }));
vi.mock('../hooks', () => ({
  MOBILE_QUERY: '(max-width: 1023.98px)',
  useMediaQuery: () => ({ isMobile: false }),
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import actionToastReducer from '../notifications/actionToastSlice';
import activityReducer, { loadActivityNow } from './activitySlice';
import Calendar from './Calendar';
import type { PlannedWindow, ScheduleEvent, SyncEvent } from './calendar/types';
import type { NowSnapshot } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const at = (dayOffset: number, hour: number) => {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

const slot = (overrides: Partial<ScheduleEvent>): ScheduleEvent => ({
  kind: 'schedule',
  schedule_id: 's1',
  name: 'Daily support digest',
  agent_id: 'a1',
  agent_name: 'Support Assistant',
  trigger_type: 'recurring',
  cron: '0 15 * * 1-5',
  timezone: 'UTC',
  origin_conversation_id: null,
  origin_conversation_name: null,
  frequent: false,
  at: at(0, 15),
  state: 'planned',
  ...overrides,
});

const sync = (dayOffset: number): SyncEvent => ({
  kind: 'sync',
  schedule_id: 'sync:daily',
  name: null,
  agent_id: null,
  agent_name: null,
  frequent: false,
  at: at(dayOffset, 3),
  state: 'planned',
  frequency: 'daily',
  sources: [
    {
      id: 'k1',
      name: 'Carrier portal',
      type: 'crawler',
      blocked: false,
      last_synced_at: at(0, 3),
    },
    {
      id: 'k2',
      name: 'Shared drive',
      type: 's3',
      blocked: true,
      last_synced_at: null,
    },
  ],
});

const WINDOW: PlannedWindow = {
  from: '',
  to: '',
  events: [
    slot({}),
    slot({
      schedule_id: 's2',
      name: 'Prospect news scan',
      at: at(0, 7),
      state: 'failed',
      run_id: 'r9',
    }),
    sync(1),
  ],
  monitors: [
    {
      monitor_id: 'm1',
      description: 'Rotterdam congestion',
      source_type: 'webpage',
      status: 'active',
      interval_seconds: 1800,
      conversation_id: 'c1',
      starts_at: at(-2, 0),
      ends_at: at(3, 0),
      last_checked_at: null,
    },
  ],
  truncated: [],
};

describe('Calendar page', () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    activity.planned.mockReset().mockResolvedValue(WINDOW);
    schedules.getRun.mockReset().mockResolvedValue({
      run: {
        id: 'r9',
        schedule_id: 's2',
        status: 'failed',
        scheduled_for: at(0, 7),
        trigger_source: 'cron',
        output_truncated: false,
        prompt_tokens: 0,
        generated_tokens: 0,
      },
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  // A test replaces the monitors store with `{ type: 'test/monitors' }`.
  const monitorsState = (status: string) => ({
    byId: { m1: { monitor_id: 'm1', status } },
    order: ['m1'],
    loaded: true,
    loading: false,
    error: null,
  });
  const render = async () => {
    const store = configureStore({
      reducer: {
        activity: activityReducer,
        actionToast: actionToastReducer,
        preference: () => ({ token: 'tok' }),
        schedules: (s = {}) => s,
        monitors: (
          s = monitorsState('active'),
          action: { type: string; payload?: unknown },
        ) => (action.type === 'test/monitors' ? action.payload : s),
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <TooltipProvider>
            <MemoryRouter>
              <Calendar />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
    return store;
  };
  const slotButton = (name: string) =>
    Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[data-state]'),
    ).find((b) => b.textContent?.includes(name)) as HTMLButtonElement;

  it('asks for the week and draws its slots by state', async () => {
    await render();
    const [from, to] = activity.planned.mock.calls[0];
    expect(
      (to as Date).getTime() - (from as Date).getTime(),
    ).toBeGreaterThanOrEqual(6.9 * 86_400_000);
    expect(slotButton('Daily support digest').dataset.state).toBe('planned');
    expect(slotButton('Prospect news scan').dataset.state).toBe('failed');
    expect(container.textContent).toContain('Rotterdam congestion');
  });

  it('titles the week day-first in English', async () => {
    await render();
    const monday = new Date();
    monday.setHours(0, 0, 0, 0);
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7));
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    expect(container.textContent).toContain(
      new Intl.DateTimeFormat('en-GB', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
      }).formatRange(monday, sunday),
    );
  });

  it("carries a cut-off monitor's description in full", async () => {
    await render();
    expect(
      container.querySelector('button [title="Rotterdam congestion"]'),
    ).not.toBeNull();
  });

  it('reloads when a planned slot is due to turn missed', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      const soon = new Date(Date.now() + 2 * 60_000).toISOString();
      activity.planned.mockResolvedValue({
        ...WINDOW,
        events: [slot({ at: soon })],
      });
      await render();
      expect(activity.planned).toHaveBeenCalledTimes(1);
      // The slot's time plus the 10-minute grace, and nothing loads before.
      await act(async () => vi.advanceTimersByTime(11 * 60_000));
      expect(activity.planned).toHaveBeenCalledTimes(1);
      await act(async () => vi.advanceTimersByTime(60_000));
      expect(activity.planned).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('keeps its reload timer after a reload fails', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] });
    try {
      const soon = new Date(Date.now() + 2 * 60_000).toISOString();
      activity.planned.mockResolvedValue({
        ...WINDOW,
        events: [slot({ at: soon })],
      });
      await render();
      activity.planned.mockRejectedValueOnce(new Error('blip'));
      await act(async () => vi.advanceTimersByTime(12 * 60_000));
      expect(activity.planned).toHaveBeenCalledTimes(2);
      // The page still shows the last window; the timer must come back.
      await act(async () => vi.advanceTimersByTime(2 * 60_000));
      expect(activity.planned).toHaveBeenCalledTimes(3);
    } finally {
      vi.useRealTimers();
    }
  });

  const syncButton = () =>
    container.querySelector<HTMLButtonElement>('button[data-kind="sync"]');

  it('draws a knowledge sync at its time and opens its sources', async () => {
    await render();
    const button = syncButton()!;
    expect(button.textContent).toContain('activity.now.syncBatch.daily');
    await act(async () => button.click());
    const panel = document.querySelector('[data-slot="sheet-content"]')!;
    expect(panel.textContent).toContain('Carrier portal');
    expect(panel.textContent).toContain('Shared drive');
    expect(panel.textContent).toContain('activity.calendar.needsReconnecting');
    expect(panel.querySelector('a[href="/settings/knowledge"]')).not.toBeNull();
    // A sync isn't a schedule: no Run now.
    expect(panel.textContent).not.toContain('agents.schedules.runNow');
  });

  it('hides knowledge syncs with their chip, in every view', async () => {
    await render();
    const chip = () =>
      Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent === 'activity.calendar.knowledgeSyncs',
      ) as HTMLButtonElement;
    await act(async () => chip().click());
    expect(syncButton()).toBeNull();
    await act(async () => chip().click());
    const agenda = Array.from(
      container.querySelectorAll('[role="radio"]'),
    ).find(
      (b) => b.textContent === 'activity.calendar.views.agenda',
    ) as HTMLElement;
    await act(async () => agenda.click());
    expect(chip()).toBeDefined();
    expect(container.textContent).toContain('activity.now.syncBatch.daily');
  });

  it('shows monitors in the month too, and hides them with their chip', async () => {
    await render();
    const month = Array.from(container.querySelectorAll('[role="radio"]')).find(
      (b) => b.textContent === 'activity.calendar.views.month',
    ) as HTMLElement;
    await act(async () => month.click());
    expect(container.textContent).toContain('Rotterdam congestion');
    const chip = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'activity.calendar.monitors',
    ) as HTMLButtonElement;
    await act(async () => chip.click());
    expect(container.textContent).not.toContain('Rotterdam congestion');
  });

  it('asks again when a monitor is paused, cancelled or ends', async () => {
    // Another tab cancelled it; the monitors store hears monitor.updated.
    const store = await render();
    const calls = activity.planned.mock.calls.length;
    await act(async () => {
      store.dispatch({
        type: 'test/monitors',
        payload: monitorsState('active'),
      });
    });
    expect(activity.planned).toHaveBeenCalledTimes(calls);
    await act(async () => {
      store.dispatch({
        type: 'test/monitors',
        payload: monitorsState('cancelled'),
      });
    });
    expect(activity.planned).toHaveBeenCalledTimes(calls + 1);
  });

  it('asks again only when activity may have changed', async () => {
    const store = await render();
    const fetched = (reason: 'event' | 'poll') =>
      act(async () => {
        store.dispatch(
          loadActivityNow.fulfilled(
            { running: [] } as unknown as NowSnapshot,
            'req',
            reason,
          ),
        );
      });
    await fetched('poll');
    const calls = activity.planned.mock.calls.length;
    // The minute poll brings the same snapshot: nothing to recompute.
    await fetched('poll');
    expect(activity.planned).toHaveBeenCalledTimes(calls);
    await fetched('event');
    expect(activity.planned).toHaveBeenCalledTimes(calls + 1);
  });

  it('asks a phone for the agenda first, not the week', async () => {
    // useMediaQuery settles after the first render; a phone fetched the
    // week window, then the agenda's.
    const matchMedia = vi
      .spyOn(window, 'matchMedia')
      .mockImplementation(
        (query: string) =>
          ({ matches: query.includes('max-width'), media: query }) as never,
      );
    try {
      await render();
      const [from, to] = activity.planned.mock.calls[0];
      expect(
        Math.round(
          ((to as Date).getTime() - (from as Date).getTime()) / 86_400_000,
        ),
      ).toBe(14);
    } finally {
      matchMedia.mockRestore();
    }
  });

  it('lists a summed-up day as one row with its span and count', async () => {
    const frequent = {
      schedule_id: 'f1',
      name: 'Inbox triage',
      frequent: true,
    };
    activity.planned.mockReset().mockResolvedValue({
      ...WINDOW,
      events: [
        slot({
          ...frequent,
          state: 'success',
          at: at(0, 0),
          until: at(0, 9),
          count: 10,
        }),
        slot({ ...frequent, state: 'failed', at: at(0, 10), run_id: 'r1' }),
      ],
    });
    await render();
    const block = container.querySelector<HTMLButtonElement>(
      'button[aria-label="activity.calendar.block"]',
    )!;
    await act(async () => block.click());
    const panel = document.querySelector('[data-slot="sheet-content"]')!;
    expect(panel.querySelector('[data-slot="count"]')?.textContent).toBe('11');
    expect(panel.textContent).toContain('activity.calendar.slotCount');
    expect(panel.textContent).toContain('–');
  });

  it("treats a paused frequent schedule's day as paused, as its slots are", async () => {
    // A single slot of a paused schedule hides Run now; its day block must too.
    const frequent = {
      schedule_id: 'f1',
      name: 'Inbox triage',
      frequent: true,
    };
    activity.planned.mockReset().mockResolvedValue({
      ...WINDOW,
      events: [
        slot({ ...frequent, state: 'paused', at: at(0, 10) }),
        slot({ ...frequent, state: 'paused', at: at(0, 11) }),
      ],
    });
    await render();
    const block = container.querySelector<HTMLButtonElement>(
      'button[aria-label="activity.calendar.block"]',
    )!;
    await act(async () => block.click());
    const panel = document.querySelector('[data-slot="sheet-content"]')!;
    expect(panel.textContent).toContain('activity.calendar.pausedNote');
    expect(panel.textContent).not.toContain('agents.schedules.runNow');
  });

  const next = () =>
    container.querySelector<HTMLButtonElement>(
      'button[aria-label="activity.calendar.next"]',
    )!;

  it('shows loading, not an empty week, while another week loads', async () => {
    await render();
    activity.planned.mockReturnValueOnce(new Promise(() => undefined));
    await act(async () => next().click());
    expect(
      container.querySelector('[data-slot="loading-state"]'),
    ).not.toBeNull();
    expect(slotButton('Daily support digest')).toBeUndefined();
  });

  it('shows the error with Retry when another week fails to load', async () => {
    await render();
    activity.planned.mockRejectedValueOnce(new Error('down'));
    await act(async () => next().click());
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('activity.calendar.loadError');
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    // The next week loads: no error, no spinner (its slots are elsewhere).
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[data-slot="loading-state"]')).toBeNull();
  });

  it('keeps the week when a refresh of it fails', async () => {
    const store = await render();
    activity.planned.mockRejectedValueOnce(new Error('down'));
    await act(async () => {
      store.dispatch(
        loadActivityNow.fulfilled(
          { running: [] } as unknown as NowSnapshot,
          'r2',
          'event',
        ),
      );
    });
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(slotButton('Daily support digest')).toBeDefined();
  });

  it("does not carry one schedule's Run now over to another", async () => {
    activity.planned.mockReset().mockResolvedValue({
      ...WINDOW,
      events: [
        slot({}),
        slot({
          schedule_id: 's3',
          name: 'Weekly carrier review',
          at: at(0, 11),
        }),
      ],
    });
    schedules.runNow.mockReset().mockResolvedValue({ run: { id: 'r1' } });
    await render();
    const panel = () => document.querySelector('[data-slot="sheet-content"]');
    const runNow = () =>
      Array.from(panel()!.querySelectorAll('button')).find((b) =>
        b.textContent?.includes('agents.schedules.runNow'),
      )!;

    await act(async () => slotButton('Daily support digest').click());
    await act(async () => runNow().click());
    expect(panel()?.textContent).toContain('activity.calendar.queued');
    await act(async () => {
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }),
      );
    });
    await act(async () => slotButton('Weekly carrier review').click());
    expect(panel()?.textContent).not.toContain('activity.calendar.queued');
    expect(runNow().disabled).toBe(false);
    expect(schedules.runNow).toHaveBeenCalledTimes(1);
  });

  it('says a refused Run now in a toast and leaves the button ready', async () => {
    schedules.runNow.mockReset().mockRejectedValue(new Error('in flight'));
    const store = await render();
    const panel = () => document.querySelector('[data-slot="sheet-content"]');
    const runNow = () =>
      Array.from(panel()!.querySelectorAll('button')).find((b) =>
        b.textContent?.includes('agents.schedules.runNow'),
      )!;

    await act(async () => slotButton('Daily support digest').click());
    await act(async () => runNow().click());
    expect(store.getState().actionToast.current).toMatchObject({
      variant: 'destructive',
      message: 'activity.calendar.runNowError',
    });
    expect(panel()?.textContent).not.toContain('activity.calendar.queued');
    expect(runNow().disabled).toBe(false);
  });

  it('keeps a day summary under "Hide past" while it has slots to come', async () => {
    activity.planned.mockReset().mockResolvedValue({
      ...WINDOW,
      events: [
        slot({
          schedule_id: 'f1',
          name: 'Inbox triage',
          frequent: true,
          at: at(0, 0),
          until: new Date(Date.now() + 3_600_000).toISOString(),
          count: 24,
        }),
      ],
    });
    await render();
    const hidePast = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'activity.calendar.hidePast',
    )!;
    await act(async () => hidePast.click());
    expect(
      container.querySelector('button[aria-label="activity.calendar.block"]'),
    ).not.toBeNull();
  });

  it('opens a planned slot in the schedule panel', async () => {
    await render();
    await act(async () => slotButton('Daily support digest').click());
    const panel = document.querySelector('[data-slot="sheet-content"]');
    expect(panel?.textContent).toContain('activity.calendar.openSchedule');
  });

  it("links a chat-made slot's panel back to its chat as a text link", async () => {
    activity.planned.mockReset().mockResolvedValue({
      ...WINDOW,
      events: [
        slot({
          origin_conversation_id: 'c1',
          origin_conversation_name: 'Rotterdam market check',
        }),
      ],
    });
    await render();
    await act(async () => slotButton('Daily support digest').click());
    const link = document.querySelector<HTMLAnchorElement>(
      '[data-slot="sheet-content"] a[href="/c/c1"]',
    );
    expect(link?.textContent).toBe('Rotterdam market check');
    expect(link?.dataset.variant).toBe('link');
    expect(link?.dataset.size).toBe('text');
    expect(link?.className).toContain('text-link');
    expect(link?.className).not.toContain('text-primary');
  });

  it('opens a past slot as its run', async () => {
    await render();
    await act(async () => slotButton('Prospect news scan').click());
    expect(schedules.getRun).toHaveBeenCalledWith('s2', 'r9', 'tok');
    expect(
      document.querySelector('[data-slot="sheet-content"]')?.textContent,
    ).toContain('agents.schedules.runDetails.title');
  });
});
