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

import activityReducer, { loadActivityNow } from './activitySlice';
import History, { formatDuration } from './History';
import type { HistoryRun } from './historyTypes';
import type { NowSnapshot } from './types';

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
    return store;
  };
  const row = (kind: string) =>
    container.querySelector<HTMLTableRowElement>(
      `tr[data-kind="${kind}"]`,
    ) as HTMLTableRowElement;
  const titles = () =>
    Array.from(container.querySelectorAll('tr[data-kind]')).map(
      (tr) => tr.querySelector('td:nth-child(2)')?.textContent,
    );
  const named = (...names: string[]) =>
    names.map((name) => run({ id: name, title: name }));
  /** A history call that resolves when the test says so. */
  const deferred = () => {
    let resolve!: (page: { runs: HistoryRun[]; has_more: boolean }) => void;
    const promise = new Promise<{ runs: HistoryRun[]; has_more: boolean }>(
      (r) => (resolve = r),
    );
    return { promise, resolve };
  };
  const clickLoadMore = () =>
    act(async () =>
      (
        Array.from(container.querySelectorAll('button')).find(
          (b) => b.textContent === 'activity.history.loadMore',
        ) as HTMLElement
      ).click(),
    );
  const clickKind = (kind: string) =>
    act(async () =>
      (
        Array.from(container.querySelectorAll('[role="radio"]')).find(
          (b) => b.textContent === `activity.history.kindFilters.${kind}`,
        ) as HTMLElement
      ).click(),
    );
  const newSnapshot = (store: Awaited<ReturnType<typeof render>>) =>
    act(async () => {
      store.dispatch(
        loadActivityNow.fulfilled({} as NowSnapshot, 'req', undefined),
      );
    });

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

  it('keeps loaded pages when the snapshot changes, adding new runs on top', async () => {
    activity.history
      .mockReset()
      .mockResolvedValueOnce({ runs: named('a', 'b'), has_more: true })
      .mockResolvedValueOnce({ runs: named('c', 'd'), has_more: false })
      .mockResolvedValueOnce({ runs: named('n', 'a'), has_more: true });
    const store = await render();
    await clickLoadMore();
    expect(titles()).toEqual(['a', 'b', 'c', 'd']);

    await newSnapshot(store);
    expect(activity.history.mock.calls.at(-1)?.[0]).toMatchObject({
      offset: 0,
    });
    expect(titles()).toEqual(['n', 'a', 'b', 'c', 'd']);
    // The last page was already reached; a refresh doesn't bring the button back.
    expect(container.textContent).not.toContain('activity.history.loadMore');
  });

  it('shows the latest filter when an older request answers last', async () => {
    const webhooks = deferred();
    const jobs = deferred();
    await render();
    activity.history
      .mockReturnValueOnce(webhooks.promise)
      .mockReturnValueOnce(jobs.promise);
    await clickKind('webhook');
    await clickKind('job');

    await act(async () =>
      jobs.resolve({ runs: named('job run'), has_more: false }),
    );
    await act(async () =>
      webhooks.resolve({ runs: named('webhook run'), has_more: false }),
    );
    expect(titles()).toEqual(['job run']);
  });

  it.each([
    ['refresh first', ['head', 'more']],
    ['load more first', ['more', 'head']],
  ])(
    'lists each run once when a refresh and Load more overlap (%s)',
    async (_, order) => {
      activity.history
        .mockReset()
        .mockResolvedValueOnce({ runs: named('a', 'b'), has_more: true });
      const store = await render();
      const more = deferred();
      const head = deferred();
      activity.history
        .mockReturnValueOnce(more.promise)
        .mockReturnValueOnce(head.promise);
      await clickLoadMore();
      await newSnapshot(store);

      // `n` landed between the two requests, so Load more's offset 2 now
      // starts at `b` again.
      const answers = {
        more: () => more.resolve({ runs: named('b', 'c'), has_more: true }),
        head: () => head.resolve({ runs: named('n', 'a'), has_more: true }),
      };
      for (const which of order as ('head' | 'more')[]) {
        await act(async () => answers[which]());
      }
      expect(titles()).toEqual(['n', 'a', 'b', 'c']);
    },
  );
});

describe('formatDuration', () => {
  it('reads in seconds, minutes and hours', () => {
    expect(formatDuration(8_200)).toBe('8.2 s');
    expect(formatDuration(130_000)).toBe('2 m 10 s');
    expect(formatDuration(3_840_000)).toBe('1 h 4 m');
    expect(formatDuration(null)).toBe('');
  });
});
