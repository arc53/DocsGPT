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

import activityReducer from './activitySlice';
import Calendar from './Calendar';
import type { CalendarEvent, PlannedWindow } from './calendar/types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const at = (dayOffset: number, hour: number) => {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

const slot = (overrides: Partial<CalendarEvent>): CalendarEvent => ({
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
  syncs: [],
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
