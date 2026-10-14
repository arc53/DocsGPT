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
vi.mock('../hooks', () => ({ useMediaQuery: () => ({ isMobile: false }) }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

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

  const render = async () => {
    const store = configureStore({
      reducer: {
        activity: activityReducer,
        preference: () => ({ token: 'tok' }),
        schedules: (s = {}) => s,
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

  it('opens a planned slot in the schedule panel', async () => {
    await render();
    await act(async () => slotButton('Daily support digest').click());
    const panel = document.querySelector('[data-slot="sheet-content"]');
    expect(panel?.textContent).toContain('activity.calendar.openSchedule');
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
