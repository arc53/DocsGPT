import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const runs = [
  {
    id: 'r1',
    schedule_id: 's1',
    status: 'success',
    scheduled_for: '2026-09-21T09:00:00Z',
    started_at: '2026-09-21T09:00:00Z',
    finished_at: '2026-09-21T09:00:42Z',
    trigger_source: 'cron',
    prompt_tokens: 4000,
    generated_tokens: 812,
  },
];
const { store, dispatch, thunkArgs } = vi.hoisted(() => ({
  store: {
    runs: [] as unknown[],
    end: false,
  },
  thunkArgs: [] as Array<{ id: string; offset?: number }>,
  // Each dispatch resolves (or rejects) the way the next test sets it.
  dispatch: vi.fn(),
}));

vi.mock('./schedulesSlice', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./schedulesSlice')>()),
  loadRunsForSchedule: (args: { id: string; offset?: number }) => {
    thunkArgs.push(args);
    return { type: 'loadRuns', args };
  },
}));

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: 't' },
      schedules: {
        byAgent: {},
        runsBySchedule: { s1: store.runs },
        runsEndBySchedule: { s1: store.end },
      },
    }),
  useDispatch: () => dispatch,
}));

import RunLog from './RunLog';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('RunLog', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    store.runs = runs;
    store.end = true;
    thunkArgs.length = 0;
    dispatch.mockReset();
    dispatch.mockImplementation(() => ({ unwrap: () => Promise.resolve() }));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('opens a run from its whole row, with duration and grouped tokens', async () => {
    const onSelect = vi.fn();
    await act(async () => {
      root.render(<RunLog scheduleId="s1" onSelect={onSelect} />);
    });
    const heads = Array.from(container.querySelectorAll('th')).map(
      (th) => th.textContent,
    );
    expect(heads).toContain('agents.schedules.runLog.duration');
    // The default table head, not the eyebrow.
    expect(container.querySelector('th')!.className).not.toContain('uppercase');
    const row = container.querySelector('tbody tr') as HTMLTableRowElement;
    expect(row.textContent).toContain('42.0 s');
    expect(row.textContent).toContain('4.8k');
    expect(row.querySelector('svg.lucide-chevron-right')).not.toBeNull();
    // No separate Details link: the row is the target.
    expect(row.querySelector('button')).toBeNull();
    await act(async () => row.click());
    expect(onSelect).toHaveBeenCalledWith(runs[0]);
  });

  const many = (n: number) =>
    Array.from({ length: n }, (_, i) => ({ ...runs[0], id: `r${i}` }));
  const flush = async () => {
    for (let i = 0; i < 4; i += 1) await act(async () => Promise.resolve());
  };
  const status = () =>
    container.querySelector('[data-slot="load-more-status"]');

  it('caps the log in an inner scroller, never on the card', async () => {
    await act(async () => root.render(<RunLog scheduleId="s1" />));
    const scroller = container.querySelector('table')!.parentElement!;
    expect(scroller.className).toContain('max-h-[45svh]');
    expect(scroller.className).toContain('overflow-y-auto');
    expect(scroller.className).toContain('scrollbar-overlay');
  });

  it('asks for the first page, then the next from where the log ends', async () => {
    store.runs = many(50);
    store.end = false;
    let reach!: () => void;
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(cb: IntersectionObserverCallback) {
          reach = () =>
            cb(
              [{ isIntersecting: true } as IntersectionObserverEntry],
              this as unknown as IntersectionObserver,
            );
        }
        observe() {}
        disconnect() {}
      },
    );
    await act(async () => root.render(<RunLog scheduleId="s1" />));
    await flush();
    expect(thunkArgs[0]).toMatchObject({ id: 's1', offset: 0 });
    await act(async () => reach());
    await flush();
    expect(thunkArgs[1]).toMatchObject({ id: 's1', offset: 50 });
    vi.unstubAllGlobals();
  });

  it('says so once the oldest run is loaded, only for a long log', async () => {
    store.runs = many(60);
    store.end = true;
    await act(async () => root.render(<RunLog scheduleId="s1" />));
    await flush();
    expect(status()!.textContent).toBe('pagination.noOlder');
    store.runs = many(3);
    await act(async () => root.render(<RunLog scheduleId="s1" key="short" />));
    await flush();
    expect(status()).toBeNull();
  });

  it('a first load that fails offers Retry instead of "no runs"', async () => {
    store.runs = [];
    dispatch.mockImplementation(() => ({
      unwrap: () => Promise.reject(new Error('down')),
    }));
    await act(async () => root.render(<RunLog scheduleId="s1" />));
    await flush();
    expect(container.textContent).toContain(
      'agents.schedules.runLog.loadFailed',
    );
    expect(container.textContent).not.toContain(
      'agents.schedules.runLog.empty',
    );
    const retry = Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    );
    expect(retry?.className).toContain('rounded-full');
  });
});
