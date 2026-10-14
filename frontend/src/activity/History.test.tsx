import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

const activity = vi.hoisted(() => ({ history: vi.fn(), now: vi.fn() }));
vi.mock('../api/services/activityService', () => ({ default: activity }));
const schedules = vi.hoisted(() => ({ getRun: vi.fn() }));
vi.mock('../api/services/schedulesService', () => ({ default: schedules }));
const traces = vi.hoisted(() => ({ last: null as unknown }));
vi.mock('../settings/traces/TraceSheet', () => ({
  default: ({ traceRef }: { traceRef: unknown }) => {
    traces.last = traceRef;
    return null;
  },
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }),
}));

import { TooltipProvider } from '@/components/ui/tooltip';

import activityReducer from './activitySlice';
import History, { formatDuration } from './History';
import type { HistoryRun } from './historyTypes';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const run = (overrides: Partial<HistoryRun>): HistoryRun => ({
  kind: 'schedule',
  id: 'r1',
  title: 'Daily support digest',
  agent_id: 'a1',
  agent_name: 'Support Assistant',
  conversation_id: null,
  conversation_name: null,
  trigger: 'cron',
  status: 'success',
  at: new Date().toISOString(),
  duration_ms: 11_100,
  tokens: 2870,
  schedule_id: 's1',
  trace_id: null,
  workflow_run_id: null,
  error_type: null,
  error: null,
  ...overrides,
});

const PAGE = {
  runs: [
    run({}),
    run({
      kind: 'webhook',
      id: 't1',
      title: 'Carrier onboarding',
      status: 'failed',
      trigger: 'webhook',
      schedule_id: null,
      trace_id: 't1',
    }),
  ],
  has_more: false,
};

describe('History page', () => {
  let container: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    activity.history.mockReset().mockResolvedValue(PAGE);
    schedules.getRun.mockReset().mockResolvedValue({
      run: {
        id: 'r1',
        schedule_id: 's1',
        status: 'success',
        scheduled_for: new Date().toISOString(),
        trigger_source: 'cron',
        output_truncated: false,
        prompt_tokens: 0,
        generated_tokens: 0,
      },
    });
    traces.last = null;
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
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <TooltipProvider>
            <MemoryRouter>
              <History />
            </MemoryRouter>
          </TooltipProvider>
        </Provider>,
      );
    });
  };
  const row = (kind: string) =>
    container.querySelector<HTMLTableRowElement>(
      `tr[data-kind="${kind}"]`,
    ) as HTMLTableRowElement;

  it('lists runs under a day heading', async () => {
    await render();
    expect(container.textContent).toContain('activity.calendar.today');
    expect(row('schedule').textContent).toContain('Daily support digest');
    expect(row('schedule').textContent).toContain('11 s');
    expect(row('webhook').textContent).toContain(
      'activity.history.status.failed',
    );
  });

  it('opens a scheduled run in its details', async () => {
    await render();
    await act(async () => row('schedule').click());
    expect(schedules.getRun).toHaveBeenCalledWith('s1', 'r1', 'tok');
  });

  it('opens a webhook run as its trace', async () => {
    await render();
    await act(async () => row('webhook').click());
    expect(traces.last).toEqual({ field: 'id', value: 't1' });
  });

  it('asks again for one kind', async () => {
    await render();
    const webhooks = Array.from(
      container.querySelectorAll('[role="radio"]'),
    ).find(
      (b) => b.textContent === 'activity.history.kindFilters.webhook',
    ) as HTMLElement;
    await act(async () => webhooks.click());
    expect(activity.history.mock.calls.at(-1)?.[0]).toMatchObject({
      kind: 'webhook',
      offset: 0,
    });
  });
});

describe('formatDuration', () => {
  it('reads in seconds, minutes and hours', () => {
    expect(formatDuration(8_200)).toBe('8.2 s');
    expect(formatDuration(130_000)).toBe('2 m 10 s');
    expect(formatDuration(3_840_000)).toBe('1 h 4 m');
    expect(formatDuration(null)).toBe('');
  });
});
