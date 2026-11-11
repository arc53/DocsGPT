import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { reason?: string }) =>
      opts?.reason ? `${key}:${opts.reason}` : key,
  }),
}));

vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

const service = vi.hoisted(() => ({
  listRuns: vi.fn(),
  create: vi.fn(),
}));
vi.mock('../../api/services/schedulesService', () => ({ default: service }));

// A plain input stands in for the time picker (see ScheduleFormModal.test).
vi.mock('@/components/ui/time-picker', () => ({
  TimePicker: () => <input data-testid="time-picker" readOnly />,
}));

import {
  sseEventReceived,
  type SSEEvent,
} from '../../notifications/notificationsSlice';
import type { Schedule, ScheduleRun } from '../types/schedule';
import ScheduleFormModal from './ScheduleFormModal';
import schedulesReducer, { createSchedule } from './schedulesSlice';
import TestRunResult from './TestRunResult';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const schedule = {
  id: 's1',
  user_id: 'u1',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Digest',
  instruction: 'Summarise the new deals.',
  status: 'active',
  cron: '0 9 * * 1',
  timezone: 'UTC',
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 0,
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
} as Schedule;

const testRun: ScheduleRun = {
  id: 'r1',
  schedule_id: 's1',
  user_id: 'u1',
  agent_id: 'a1',
  status: 'pending',
  scheduled_for: '2026-11-10T12:00:00Z',
  trigger_source: 'manual',
  output_truncated: false,
  prompt_tokens: 0,
  generated_tokens: 0,
  created_at: '2026-11-10T12:00:00Z',
  updated_at: '2026-11-10T12:00:00Z',
};

const makeStore = () =>
  configureStore({
    reducer: {
      schedules: schedulesReducer,
      preference: (state = { token: 't' }) => state,
    },
  });

const runEvent = (type: string, payload: Record<string, unknown>) =>
  sseEventReceived({
    id: `evt-${type}`,
    type,
    ts: '2026-11-10T12:00:30Z',
    payload: { schedule_id: 's1', run_id: 'r1', ...payload },
  } as SSEEvent);

describe('TestRunResult', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    service.listRuns.mockReset();
    store = makeStore();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (agentId: string | null = 'a1') => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <TestRunResult scheduleId="s1" runId="r1" agentId={agentId} />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const seed = async () => {
    await act(async () => {
      store.dispatch(
        createSchedule.fulfilled({ schedule, testRun }, 'c', {
          agentId: 'a1',
          payload: { instruction: 'x' },
          token: 't',
        }),
      );
    });
  };

  it('shows the run as running, then the agent’s reason and a way to fix it', async () => {
    await seed();
    await render();
    expect(container.textContent).toContain('agents.schedules.testRun.running');
    expect(container.querySelector('tbody tr')?.textContent).toContain(
      'agents.schedules.trigger.manual',
    );
    expect(service.listRuns).not.toHaveBeenCalled();

    const finished = {
      ...testRun,
      status: 'failed',
      error_type: 'cannot_complete',
      error: 'No CRM tool to look the account up.',
      started_at: '2026-11-10T12:00:01Z',
      finished_at: '2026-11-10T12:00:09Z',
      prompt_tokens: 900,
      generated_tokens: 40,
    };
    service.listRuns.mockResolvedValue({ runs: [finished] });
    await act(async () => {
      store.dispatch(
        runEvent('schedule.run.failed', {
          error_type: 'cannot_complete',
          error: 'No CRM tool to look the account up.',
        }),
      );
    });

    expect(container.textContent).toContain('agents.schedules.testRun.failed');
    expect(container.textContent).toContain(
      'agents.schedules.testRun.cannotComplete:No CRM tool to look the account up.',
    );
    const fix = container.querySelector('a');
    expect(fix?.textContent).toBe('agents.schedules.testRun.editAgent');
    expect(fix?.getAttribute('href')).toBe('/agents/manage/edit/a1');
    // Read once more for the duration and tokens the event doesn't carry.
    expect(service.listRuns).toHaveBeenCalledTimes(1);
    expect(container.querySelector('tbody tr')?.textContent).toContain('940');
  });

  it('says the test worked when it succeeds', async () => {
    await seed();
    await render();
    service.listRuns.mockResolvedValue({
      runs: [{ ...testRun, status: 'success' }],
    });
    await act(async () => {
      store.dispatch(runEvent('schedule.run.completed', {}));
    });
    expect(container.textContent).toContain(
      'agents.schedules.testRun.succeeded',
    );
    expect(container.querySelector('a')).toBeNull();
  });

  it('points an agentless task to the tools settings', async () => {
    await seed();
    await render(null);
    service.listRuns.mockResolvedValue({
      runs: [
        {
          ...testRun,
          agent_id: null,
          status: 'failed',
          error_type: 'cannot_complete',
          error: 'No browser tool.',
        },
      ],
    });
    await act(async () => {
      store.dispatch(
        runEvent('schedule.run.failed', {
          error_type: 'cannot_complete',
          error: 'No browser tool.',
        }),
      );
    });
    const fix = container.querySelector('a');
    expect(fix?.textContent).toBe('agents.schedules.testRun.editTools');
    expect(fix?.getAttribute('href')).toBe('/settings/tools');
  });

  it('reads a run still going again, in case its result event was missed', async () => {
    vi.useFakeTimers();
    try {
      await seed();
      await render();
      expect(service.listRuns).not.toHaveBeenCalled();
      service.listRuns.mockResolvedValue({
        runs: [{ ...testRun, status: 'success' }],
      });
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      expect(service.listRuns).toHaveBeenCalled();
      expect(container.textContent).toContain(
        'agents.schedules.testRun.succeeded',
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('loads the run when the store does not have it yet (a chat card)', async () => {
    service.listRuns.mockResolvedValue({ runs: [testRun] });
    await render();
    expect(service.listRuns).toHaveBeenCalledTimes(1);
    expect(container.querySelector('tbody tr')).not.toBeNull();
  });
});

describe('ScheduleFormModal test run', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    store = makeStore();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    onSubmit: (payload: unknown) => unknown,
    initial: Schedule | null = null,
    onClose: () => void = () => undefined,
  ) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <ScheduleFormModal
              open
              initial={initial}
              approvalTools={[]}
              onClose={onClose}
              onSubmit={onSubmit as never}
            />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === text);
  const testRunBox = () =>
    document.body.querySelector<HTMLButtonElement>('#schedule-test-run');
  const typeInstruction = async (value: string) => {
    const textarea = document.body.querySelector('textarea')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(textarea, value);
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
  const submit = async () => {
    await typeInstruction('Summarise the new deals.');
    await act(async () => button('agents.schedules.modal.create')!.click());
  };

  it('asks for a test run by default for a recurring schedule', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit);
    expect(testRunBox()?.getAttribute('data-state')).toBe('checked');
    await submit();
    expect(onSubmit.mock.calls[0][0].test_run).toBe(true);
  });

  it('leaves it off for a one-time task unless ticked', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit);
    await act(async () =>
      button('agents.schedules.modal.frequency.once')!.click(),
    );
    expect(testRunBox()?.getAttribute('data-state')).toBe('unchecked');
    await act(async () => testRunBox()!.click());
    expect(testRunBox()?.getAttribute('data-state')).toBe('checked');
  });

  it('sends none once unticked', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit);
    await act(async () => testRunBox()!.click());
    await submit();
    expect(onSubmit.mock.calls[0][0].test_run).toBeUndefined();
  });

  it('offers none when editing', async () => {
    await render(vi.fn(), schedule);
    expect(testRunBox()).toBeNull();
  });

  it('stays open on the test run, pending and then its result, until Done', async () => {
    const onClose = vi.fn();
    const onSubmit = vi.fn(async () => {
      const created = { schedule, testRun };
      store.dispatch(
        createSchedule.fulfilled(created, 'c', {
          agentId: 'a1',
          payload: { instruction: 'x' },
          token: 't',
        }),
      );
      return created;
    });
    await render(onSubmit, null, onClose);
    await submit();

    expect(document.body.textContent).toContain(
      'agents.schedules.testRun.title',
    );
    expect(document.body.textContent).toContain(
      'agents.schedules.testRun.running',
    );
    expect(document.body.querySelector('textarea')).toBeNull();

    service.listRuns.mockResolvedValue({
      runs: [{ ...testRun, status: 'success' }],
    });
    await act(async () => {
      store.dispatch(runEvent('schedule.run.completed', {}));
    });
    expect(document.body.textContent).toContain(
      'agents.schedules.testRun.succeeded',
    );
    await act(async () => button('agents.schedules.testRun.done')!.click());
    expect(onClose).toHaveBeenCalled();
  });
});
