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

import actionToastReducer from '../notifications/actionToastSlice';
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
        actionToast: actionToastReducer,
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
  const EMPTY_SNAPSHOT: NowSnapshot = {
    running: [],
    needs_you: [],
    up_next: [],
    approval_conversations: [],
    failed_conversations: [],
    stats: { next_24h: 0, failed_24h: 0 },
  };
  const newSnapshot = (store: Awaited<ReturnType<typeof render>>) =>
    act(async () => {
      store.dispatch(loadActivityNow.fulfilled(EMPTY_SNAPSHOT, 'req', 'event'));
    });

  it('lists runs under a day heading', async () => {
    await render();
    expect(container.textContent).toContain('activity.calendar.today');
    expect(row('schedule').textContent).toContain('Daily support digest');
    expect(row('schedule').textContent).toContain('11s');
    expect(row('webhook').textContent).toContain(
      'activity.history.status.failed',
    );
  });

  it('heads an older day day-first in English', async () => {
    const older = new Date();
    older.setDate(older.getDate() - 4);
    older.setHours(12, 0, 0, 0);
    activity.history.mockResolvedValue({
      runs: [run({ at: older.toISOString() })],
      has_more: false,
    });
    await render();
    expect(container.textContent).toContain(
      new Intl.DateTimeFormat('en-GB', {
        weekday: 'long',
        day: 'numeric',
        month: 'long',
      }).format(older),
    );
  });

  it('carries a cut-off title and names in full', async () => {
    activity.history.mockResolvedValue({
      runs: [run({ conversation_name: 'Rotterdam port' })],
      has_more: false,
    });
    await render();
    const cells = row('schedule').querySelectorAll('td');
    expect(cells[1].querySelector('[title]')?.getAttribute('title')).toBe(
      'Daily support digest',
    );
    expect(cells[2].querySelector('[title]')?.getAttribute('title')).toBe(
      'Support Assistant · Rotterdam port',
    );
  });

  it('opens a scheduled run in its details', async () => {
    await render();
    await act(async () => row('schedule').click());
    expect(schedules.getRun).toHaveBeenCalledWith('s1', 'r1', 'tok');
  });

  it('says a run that fails to open in a toast, leaving the list alone', async () => {
    activity.history.mockResolvedValue({ ...PAGE, has_more: true });
    const store = await render();
    schedules.getRun.mockRejectedValueOnce(new Error('gone'));
    await act(async () => row('schedule').click());
    expect(store.getState().actionToast.current).toMatchObject({
      variant: 'destructive',
      message: 'activity.history.runLoadError',
    });
    expect(container.textContent).not.toContain('pagination.olderFailed');
    expect(
      Array.from(container.querySelectorAll('button')).some(
        (b) => b.textContent === 'activity.history.loadMore',
      ),
    ).toBe(true);
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

  it("shows loading, not the last filter's runs, while a new filter loads", async () => {
    await render();
    activity.history.mockReturnValueOnce(deferred().promise);
    await clickKind('webhook');
    expect(
      container.querySelector('[data-slot="loading-state"]'),
    ).not.toBeNull();
    expect(titles()).toEqual([]);
  });

  it('retries a filter that failed to load from its start', async () => {
    await render();
    activity.history.mockRejectedValueOnce(new Error('down'));
    await clickKind('webhook');
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      'activity.history.loadError',
    );
    expect(titles()).toEqual([]);

    activity.history.mockResolvedValueOnce({
      runs: named('webhook run'),
      has_more: false,
    });
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(activity.history.mock.calls.at(-1)?.[0]).toMatchObject({
      kind: 'webhook',
      offset: 0,
    });
    expect(titles()).toEqual(['webhook run']);
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

  it('drops a pending Load more when a refresh starts the list over', async () => {
    activity.history
      .mockReset()
      .mockResolvedValueOnce({ runs: named('a', 'b'), has_more: true });
    const store = await render();
    const more = deferred();
    activity.history.mockReturnValueOnce(more.promise);
    await clickLoadMore();

    // A full page of new runs: nothing in common, so the list starts over.
    activity.history.mockResolvedValueOnce({
      runs: named('x', 'y'),
      has_more: true,
    });
    await newSnapshot(store);
    expect(titles()).toEqual(['x', 'y']);

    // Load more asked for offset 2 of the old list; its answer is stale.
    await act(async () => more.resolve({ runs: named('c'), has_more: false }));
    expect(titles()).toEqual(['x', 'y']);
    expect(container.textContent).toContain('activity.history.loadMore');
  });
});

describe('formatDuration', () => {
  it('reads in seconds, minutes and hours', () => {
    expect(formatDuration(8_200, 'en')).toBe('8.2s');
    expect(formatDuration(130_000, 'en')).toBe('2m 10s');
    expect(formatDuration(3_840_000, 'en')).toBe('1h 4m');
    expect(formatDuration(null, 'en')).toBe('');
  });

  it('rounds to whole seconds before splitting minutes', () => {
    // Rounding the remainder alone read 119.6 s as "1 m 60 s".
    expect(formatDuration(119_600, 'en')).toBe('2m 0s');
    expect(formatDuration(59_700, 'en')).toBe('1m 0s');
  });

  it("writes the units in the reader's language", () => {
    expect(formatDuration(130_000, 'ru')).toBe('2 мин 10 с');
    expect(formatDuration(130_000, 'de')).toBe('2 Min. 10 Sek.');
  });
});
