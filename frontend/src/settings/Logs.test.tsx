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

vi.mock('../hooks/useLoadMore', () => ({ useScrollSentinel: () => vi.fn() }));
vi.mock('./traces/TraceSheet', () => ({ default: () => null }));
vi.mock('../components/CopyButton', () => ({ default: () => null }));

const getLogs = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: { getLogs: (...args: unknown[]) => getLogs(...args) },
}));

import Logs from './Logs';

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

  // O4 (c): the header strip reads like TableHead on its bg-muted strip.
  it('draws the header strip text in foreground', () => {
    const header = Array.from(container.querySelectorAll('p')).find(
      (p) => p.textContent === 'settings.logs.tableHeader',
    )!;
    expect(header).toBeDefined();
    expect(header.className).toContain('text-foreground');
    expect(header.className).not.toContain('text-muted-foreground');
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
  const started = new Date(Date.now() - 65_000).toISOString();
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
