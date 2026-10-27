import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// Selectors read this state; a test bumps `activity.revision` to stand for
// the app-wide Now snapshot reloading after a live event.
const store = vi.hoisted(() => ({
  state: {
    preference: { token: 'token' },
    activity: { now: null as object | null, revision: 0 },
  },
}));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(store.state),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// The loader's 250ms hide delay would outlast the test.
vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useLoaderState: (initial: boolean) => useState(initial),
}));

// A test calls `sentinel.reach()` to stand for scrolling to the list's end;
// `enabled` says whether the list would load more there.
const sentinel = vi.hoisted(() => ({
  reach: () => undefined as void,
  enabled: false,
}));
vi.mock('../hooks/useLoadMore', () => ({
  useScrollSentinel: (onReach: () => void, enabled: boolean) => {
    sentinel.reach = onReach;
    sentinel.enabled = enabled;
    return vi.fn();
  },
}));
// The drill-down filters are URL state; these tests run without them
// (Logs.labels.test.tsx covers them under a real router).
vi.mock('react-router-dom', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-router-dom')>()),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));
vi.mock('./traces/TraceSheet', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

const getLogs = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { getLogs: (...args: unknown[]) => getLogs(...args) },
}));

import Logs, { typeFilterParams } from './Logs';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const log = {
  id: 'log-1',
  action: 'stream_answer',
  level: 'info',
  timestamp: '2026-09-30 10:00:00',
  event_type: 'chat',
  question: 'Which carriers expire this month?',
  response: 'Three carriers.',
};

describe('Logs rows', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    getLogs.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ logs: [log], has_more: false }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Logs />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('opens a row with a real button whose details are a Collapsible', async () => {
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find((el) => el.textContent?.includes('[stream_answer]'))!;
    expect(toggle).toBeDefined();
    expect(container.querySelector('[role="button"]')).toBeNull();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    )!;
    expect(body.dataset.slot).toBe('collapsible');
    expect(body.dataset.state).toBe('closed');
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
    expect(body.textContent).toContain('Three carriers.');
    // Open reads as current: header and body on secondary, not muted.
    expect(toggle.className).toContain('bg-secondary');
    expect(toggle.className).not.toContain('bg-muted');
    expect(body.querySelector('.bg-muted.rounded-b-xl')).toBeNull();
    expect(body.querySelector('.bg-secondary.rounded-b-xl')).not.toBeNull();
    // The hover fill is for closed rows only: under an open row it would show
    // through the secondary tint and drop the meta text to 3.99:1.
    const row = toggle.parentElement!;
    expect(row.className.split(' ')).not.toContain('hover:bg-accent');
    await act(async () => toggle.click());
    expect(row.className.split(' ')).toContain('hover:bg-accent');
    expect(body.dataset.state).toBe('closed');
  });

  // A log table is a place on the page: a subtle Card, with no muted header
  // strip (the page or section heading above already names it).
  it('frames the rows in a subtle Card with no header strip', () => {
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find((el) => el.textContent?.includes('[stream_answer]'))!;
    const panel = toggle.closest<HTMLElement>(
      '[data-slot="card"][data-variant="subtle"]',
    );
    expect(panel).not.toBeNull();
    expect(panel!.querySelector('.bg-muted')).toBeNull();
  });

  // The question is what a person wrote: proportional, and it fills the rest
  // of the header row instead of wrapping at a fixed width.
  it('sets the question in sans across the rest of the row', () => {
    const question = Array.from(container.querySelectorAll('span')).find(
      (span) => span.textContent === log.question,
    )!;
    expect(question).toBeDefined();
    const classes = question.className.split(' ');
    expect(classes).toContain('font-sans');
    expect(classes).toContain('flex-1');
    expect(classes).toContain('min-w-0');
    expect(question.className).not.toMatch(/\bmax-w-/);
  });

  // V3: the text and JSON blocks of an open row are ui/code-block CodeBlocks
  // (subtle on the open row), one 16px line-height, no leading-relaxed.
  it('shows the open row blocks as subtle CodeBlocks', async () => {
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find((el) => el.textContent?.includes('[stream_answer]'))!;
    await act(async () => toggle.click());
    const blocks = Array.from(
      container.querySelectorAll<HTMLElement>('pre[data-slot="code-block"]'),
    );
    const response = blocks.find((b) => b.textContent === 'Three carriers.')!;
    expect(response).toBeDefined();
    expect(response.className).not.toContain('leading-relaxed');
    const card = response.closest('[data-slot="card"]')!;
    expect(card.getAttribute('data-variant')).toBe('subtle');
  });
});

describe('Logs load failure', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getLogs.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('shows a failed first page as an error with Retry, not "no logs"', async () => {
    getLogs.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({}),
    });
    await act(async () => root.render(<Logs />));
    const state = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"][data-tone="destructive"]',
    )!;
    expect(state).not.toBeNull();
    expect(state.textContent).toContain('settings.logs.loadError');
    expect(container.textContent).not.toContain('settings.logs.noLogs');

    getLogs.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ logs: [log], has_more: false }),
    });
    const retry = Array.from(state.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(getLogs).toHaveBeenCalledTimes(2);
    expect(
      container.querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).toBeNull();
    expect(container.textContent).toContain('[stream_answer]');
  });
});

describe('Logs running rows', () => {
  let container: HTMLDivElement;
  let root: Root;
  const page = (logs: object[]) => ({
    ok: true,
    json: () => Promise.resolve({ logs, has_more: false }),
  });
  // The clock is pinned (beforeEach), so an elapsed time reads the same
  // however long the suite took to get here.
  const NOW = Date.parse('2026-10-15T12:00:00Z');
  const started = new Date(NOW - 65_000).toISOString();
  const answer = {
    id: 'chat-run-1',
    action: 'answer',
    level: 'info',
    timestamp: started,
    started_at: started,
    event_type: 'chat',
    question: 'Where is order 4411?',
    running: true,
    origin: 'api',
  };
  const workflow = {
    id: 'workflow-r1',
    action: 'workflow_run',
    level: 'info',
    timestamp: started,
    started_at: started,
    event_type: 'workflow',
    question: 'Renewal flow',
    running: true,
    workflow_progress: {
      done: 2,
      total: 5,
      current: { node_id: 'n3', title: 'Draft reply', type: 'agent' },
    },
  };

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    getLogs.mockReset();
    store.state.activity.now = null;
    store.state.activity.revision = 0;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
  });

  it('marks a run that is still going, with who started it and its step', async () => {
    getLogs.mockResolvedValue(page([answer, workflow]));
    await act(async () => root.render(<Logs />));
    // Log rows, not the filter selects (both expand).
    const rows = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).filter((el) => el.textContent?.includes('['));
    expect(rows[0].textContent).toContain('settings.logs.running');
    expect(rows[0].textContent).toContain('settings.logs.origin.api');
    expect(rows[0].textContent).toContain('1:05');
    expect(rows[1].textContent).toContain('activity.now.stepOf');
    expect(rows[1].textContent).toContain('Draft reply');
  });

  it('says which step a failed workflow run stopped at, and nothing for a finished one', async () => {
    const ended = {
      ...workflow,
      running: false,
      finished_at: started,
      workflow_progress: {
        done: 3,
        total: null,
        current: { node_id: 'n4', title: 'Engineering answer', type: 'agent' },
      },
    };
    getLogs.mockResolvedValue(
      page([
        { ...ended, id: 'workflow-f1', level: 'error', status: 'failed' },
        { ...ended, id: 'workflow-c1', status: 'completed' },
      ]),
    );
    await act(async () => root.render(<Logs />));
    const rows = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).filter((el) => el.textContent?.includes('['));
    expect(rows[0].textContent).toContain('settings.logs.failedAtStep');
    expect(rows[0].textContent).toContain('Engineering answer');
    expect(rows[0].textContent).not.toContain('settings.logs.running');
    expect(rows[1].textContent).not.toContain('settings.logs.failedAt');
    expect(rows[1].textContent).not.toContain('Engineering answer');
  });

  it('refreshes the first page when activity changes', async () => {
    getLogs.mockResolvedValue(page([answer]));
    await act(async () => root.render(<Logs />));
    expect(container.textContent).toContain('settings.logs.running');

    getLogs.mockResolvedValue(
      page([{ ...log, id: 'chat-9', timestamp: new Date().toISOString() }]),
    );
    store.state.activity.now = { running: [] };
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    expect(getLogs).toHaveBeenCalledTimes(2);
    expect(getLogs.mock.calls[1][0].page).toBe(1);
    // The run ended: its row gives way to the finished one.
    expect(container.textContent).not.toContain('settings.logs.running');
    expect(container.textContent).toContain('[stream_answer]');
  });

  it('drops an older refresh that answers after a newer one', async () => {
    // The poll and a revision can each start a refresh; the older one,
    // read before the run ended, must not mark it running again.
    getLogs.mockResolvedValue(page([answer]));
    await act(async () => root.render(<Logs />));

    let answerOlder: (value: unknown) => void = () => undefined;
    getLogs.mockReturnValueOnce(
      new Promise((resolve) => (answerOlder = resolve)),
    );
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));

    getLogs.mockResolvedValueOnce(
      page([{ ...log, id: 'chat-9', timestamp: new Date().toISOString() }]),
    );
    store.state.activity.now = { running: [] };
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    expect(container.textContent).not.toContain('settings.logs.running');

    await act(async () => answerOlder(page([answer])));
    expect(container.textContent).not.toContain('settings.logs.running');
    expect(container.textContent).toContain('[stream_answer]');
  });

  it('refreshes a run on a later page when activity changes', async () => {
    const finished = (n: number) => ({
      ...log,
      id: `chat-${n}`,
      timestamp: new Date(Date.now() - n * 1000).toISOString(),
    });
    const firstPage = Array.from({ length: 10 }, (_, i) => finished(i));
    const schedule = {
      ...workflow,
      id: 'schedule-77',
      action: 'schedule_run',
      event_type: 'schedule',
      timestamp: started,
      workflow_progress: undefined,
    };
    getLogs.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ logs: firstPage, has_more: true }),
    });
    await act(async () => root.render(<Logs />));
    getLogs.mockResolvedValueOnce(page([schedule]));
    await act(async () => sentinel.reach());
    expect(container.textContent).toContain('settings.logs.running');

    // The schedule run ended; the refresh reads both loaded pages at once.
    getLogs.mockResolvedValueOnce(
      page([...firstPage, { ...schedule, running: false }]),
    );
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    const refresh = getLogs.mock.calls[2][0];
    expect([refresh.page, refresh.page_size]).toEqual([1, 20]);
    expect(container.textContent).not.toContain('settings.logs.running');
  });

  it('lists a run as soon as it starts', async () => {
    // A start doesn't move the revision (Calendar and History have nothing
    // new), but the Logs list has a running row to show.
    getLogs.mockResolvedValue(page([log]));
    await act(async () => root.render(<Logs />));
    getLogs.mockResolvedValue(page([answer, log]));
    store.state.activity.now = {
      running: [{ kind: 'chat', id: 'm1', title: null }],
    };
    await act(async () => root.render(<Logs />));
    expect(getLogs).toHaveBeenCalledTimes(2);
    expect(container.textContent).toContain('settings.logs.running');
  });

  it('leaves the list alone when a run only moves a step', async () => {
    store.state.activity.now = {
      running: [{ kind: 'workflow', id: 'w1', title: null }],
    };
    getLogs.mockResolvedValue(page([workflow]));
    await act(async () => root.render(<Logs />));
    store.state.activity.now = {
      running: [
        {
          kind: 'workflow',
          id: 'w1',
          title: null,
          workflow_progress: { done: 3, total: 5, current: null },
        },
      ],
    };
    await act(async () => root.render(<Logs />));
    expect(getLogs).toHaveBeenCalledTimes(1);
  });

  it('can reach every row again after more came in than a refresh reads', async () => {
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    getLogs.mockResolvedValueOnce(
      page([{ ...log, id: 'old', timestamp: at(600) }]),
    );
    await act(async () => root.render(<Logs />));
    expect(sentinel.enabled).toBe(false);

    // Eleven answers finished; the refresh reads the newest ten.
    const newest = Array.from({ length: 10 }, (_, i) => ({
      ...log,
      id: `new-${i}`,
      timestamp: at(i),
    }));
    getLogs.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ logs: newest, has_more: true }),
    });
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    expect(sentinel.enabled).toBe(true);
    getLogs.mockResolvedValueOnce(
      page([{ ...log, id: 'new-10', timestamp: at(10) }]),
    );
    await act(async () => sentinel.reach());
    expect(getLogs.mock.calls[2][0]).toMatchObject({ page: 2, page_size: 10 });
  });

  it('drops a Load more that was out when a refresh reset the pages', async () => {
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    const rows = (prefix: string, from: number) =>
      Array.from({ length: 10 }, (_, i) => ({
        ...log,
        id: `${prefix}-${i}`,
        question: `${prefix} question ${i}`,
        timestamp: at(from + i),
      }));
    const more = (logs: object[], has_more: boolean) => ({
      ok: true,
      json: () => Promise.resolve({ logs, has_more }),
    });
    getLogs.mockResolvedValueOnce(more(rows('old', 600), true));
    await act(async () => root.render(<Logs />));

    // Load more asks for page 2 and is still out...
    let answerStale: (value: unknown) => void = () => undefined;
    getLogs.mockReturnValueOnce(
      new Promise((resolve) => (answerStale = resolve)),
    );
    await act(async () => sentinel.reach());
    // ...when ten new answers finish and the refresh starts the pages over.
    getLogs.mockResolvedValueOnce(more(rows('new', 0), true));
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    // Its page 2 was read before the new rows shifted the paging.
    await act(async () => answerStale(more(rows('stale', 700), false)));

    expect(container.textContent).not.toContain('stale question');
    expect(sentinel.enabled).toBe(true);
  });

  it('refreshes a run past the hundredth row', async () => {
    // Rows 0-109 newest first; row 105 is a schedule run on page 11.
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    const rows = Array.from({ length: 110 }, (_, n) =>
      n === 105
        ? {
            ...workflow,
            id: 'schedule-105',
            action: 'schedule_run',
            event_type: 'schedule',
            timestamp: at(n),
            workflow_progress: undefined,
          }
        : { ...log, id: `chat-${n}`, timestamp: at(n) },
    );
    let ended = false;
    getLogs.mockImplementation(
      async ({
        page: number,
        page_size: size,
      }: {
        page: number;
        page_size: number;
      }) => {
        const all = rows.map((row) =>
          ended && row.id === 'schedule-105' ? { ...row, running: false } : row,
        );
        const slice = all.slice((number - 1) * size, number * size);
        return {
          ok: true,
          json: () =>
            Promise.resolve({
              logs: slice,
              has_more: number * size < all.length,
            }),
        };
      },
    );
    await act(async () => root.render(<Logs />));
    for (let n = 2; n <= 11; n++) await act(async () => sentinel.reach());
    expect(container.textContent).toContain('settings.logs.running');

    ended = true;
    getLogs.mockClear();
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    const asked = getLogs.mock.calls.map(([q]) => [q.page, q.page_size]);
    expect(asked).toEqual([
      [1, 100],
      [2, 100],
    ]);
    expect(container.textContent).not.toContain('settings.logs.running');
  });

  it('reads again only down to the deepest page with a run', async () => {
    // Rows 0-29 newest first; row 2, on page 1, is a run that goes on.
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    const rows = Array.from({ length: 30 }, (_, n) =>
      n === 2
        ? { ...answer, id: 'chat-run-2', timestamp: at(n) }
        : { ...log, id: `chat-${n}`, timestamp: at(n) },
    );
    getLogs.mockImplementation(
      async ({
        page: number,
        page_size: size,
      }: {
        page: number;
        page_size: number;
      }) => ({
        ok: true,
        json: () =>
          Promise.resolve({
            logs: rows.slice((number - 1) * size, number * size),
            has_more: number * size < rows.length,
          }),
      }),
    );
    await act(async () => root.render(<Logs />));
    for (let n = 2; n <= 3; n++) await act(async () => sentinel.reach());

    getLogs.mockClear();
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    const asked = getLogs.mock.calls.map(([q]) => [q.page, q.page_size]);
    expect(asked).toEqual([[1, 10]]);
    expect(container.textContent).toContain('settings.logs.running');
  });

  it('places a running webhook row by time across a refresh read in parts', async () => {
    // Rows 0-149 newest first; row 145, on page 15, is a run that goes on,
    // so the refresh reads two 100-row parts. The server adds a webhook run
    // older than every loaded row to part 1 only, at its end: row 100, on
    // page 11, which the merge doesn't re-sort.
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    const rows = Array.from({ length: 150 }, (_, n) =>
      n === 145
        ? { ...answer, id: 'chat-run-145', timestamp: at(n) }
        : { ...log, id: `chat-${n}`, question: `#${n}#`, timestamp: at(n) },
    );
    const webhook = {
      ...answer,
      id: 'webhook-run-w1',
      action: 'webhook_run',
      event_type: 'webhook',
      question: 'Inbound hook',
      timestamp: at(200),
      started_at: at(200),
    };
    let withWebhook = false;
    getLogs.mockImplementation(
      async ({
        page: number,
        page_size: size,
      }: {
        page: number;
        page_size: number;
      }) => ({
        ok: true,
        json: () =>
          Promise.resolve({
            logs: [
              ...rows.slice((number - 1) * size, number * size),
              ...(withWebhook && number === 1 ? [webhook] : []),
            ],
            has_more: number * size < rows.length,
          }),
      }),
    );
    await act(async () => root.render(<Logs />));
    for (let n = 2; n <= 15; n++) await act(async () => sentinel.reach());

    withWebhook = true;
    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    const text = container.textContent ?? '';
    expect(text.indexOf('Inbound hook')).toBeGreaterThan(text.indexOf('#149#'));
  });

  it('keeps only the loaded rows when a refresh reads past them', async () => {
    // 300 rows newest first; row 105, on page 11, is a run that goes on.
    // Eleven pages need 110 rows, but the refresh reads two 100-row pages.
    const at = (n: number) => new Date(Date.now() - n * 1000).toISOString();
    const rows = Array.from({ length: 300 }, (_, n) =>
      n === 105
        ? { ...answer, id: 'chat-run-105', timestamp: at(n) }
        : { ...log, id: `chat-${n}`, question: `#${n}#`, timestamp: at(n) },
    );
    getLogs.mockImplementation(
      async ({
        page: number,
        page_size: size,
      }: {
        page: number;
        page_size: number;
      }) => ({
        ok: true,
        json: () =>
          Promise.resolve({
            logs: rows.slice((number - 1) * size, number * size),
            has_more: number * size < rows.length,
          }),
      }),
    );
    await act(async () => root.render(<Logs />));
    for (let n = 2; n <= 11; n++) await act(async () => sentinel.reach());
    expect(container.textContent).toContain('#109#');
    expect(container.textContent).not.toContain('#110#');

    store.state.activity.revision += 1;
    await act(async () => root.render(<Logs />));
    expect(container.textContent).toContain('#109#');
    expect(container.textContent).not.toContain('#150#');

    getLogs.mockClear();
    await act(async () => sentinel.reach());
    expect(getLogs.mock.calls[0][0]).toMatchObject({ page: 12, page_size: 10 });
    expect(container.textContent).toContain('#119#');
  });

  it('polls a run with the token in use now', async () => {
    // A signed-in session's token is renewed while the page stays open.
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(NOW);
    getLogs.mockResolvedValue(page([answer]));
    await act(async () => root.render(<Logs />));
    store.state.preference.token = 'renewed';
    try {
      await act(async () => root.render(<Logs />));
      getLogs.mockClear();
      await act(async () => vi.advanceTimersByTime(30_000));
      expect(getLogs).toHaveBeenCalledTimes(1);
      expect(getLogs.mock.calls[0][1]).toBe('renewed');
    } finally {
      store.state.preference.token = 'token';
    }
  });

  // IN-17: the account's copy belongs to Settings › Logs; an agent's Logs
  // page names its own block.
  it("prints the account subtitle in Settings, not on an agent's page", async () => {
    getLogs.mockResolvedValue(page([answer]));
    await act(async () => root.render(<Logs />));
    expect(container.textContent).toContain('settings.logs.subtitle');
    await act(async () => root.render(<Logs agentId="agent-1" />));
    expect(container.textContent).not.toContain('settings.logs.subtitle');
  });

  it('leaves the first page alone when the snapshot changes but activity did not', async () => {
    // Opening a chat patches the snapshot; the minute poll may replace it
    // with an equal one. Neither is news for the logs.
    getLogs.mockResolvedValue(page([answer]));
    await act(async () => root.render(<Logs />));
    store.state.activity.now = { running: [] };
    await act(async () => root.render(<Logs />));
    expect(getLogs).toHaveBeenCalledTimes(1);
  });
});

describe('Logs chat row context', () => {
  let container: HTMLDivElement;
  let root: Root;

  const chat = {
    ...log,
    conversation_id: 'c0ffee00-0000-4000-8000-000000000001',
    passthrough: { user_id: 'emp-42', office: 'Berlin' },
    feedback: { text: 'dislike' },
  };

  beforeEach(async () => {
    getLogs.mockReset();
    getLogs.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ logs: [chat], has_more: false }),
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => root.render(<Logs agentId="agent-1" />));
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('marks a rated answer in the row header', () => {
    expect(
      container.querySelector('[aria-label="settings.logs.feedback.dislike"]'),
    ).not.toBeNull();
  });

  it('shows the passthrough values and the rating, not the conversation', async () => {
    const toggle = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-expanded]'),
    ).find((el) => el.textContent?.includes('[stream_answer]'))!;
    await act(async () => toggle.click());
    expect(container.textContent).toContain('user_id=emp-42, office=Berlin');
    expect(container.textContent).toContain('settings.logs.detail.feedback');
    expect(container.textContent).not.toContain(chat.conversation_id);
  });
});

describe('typeFilterParams', () => {
  it('asks for rated chat turns for Liked and Disliked', () => {
    expect(typeFilterParams('like')).toEqual({ feedback: 'like' });
    expect(typeFilterParams('dislike')).toEqual({ feedback: 'dislike' });
  });

  it('passes an event type through and nothing for all', () => {
    expect(typeFilterParams('chat')).toEqual({ event_type: 'chat' });
    expect(typeFilterParams('all')).toEqual({});
  });
});
