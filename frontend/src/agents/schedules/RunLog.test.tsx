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
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: 't' },
      schedules: { byAgent: {}, runsBySchedule: { s1: runs } },
    }),
  useDispatch: () => vi.fn(),
}));

import RunLog from './RunLog';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('RunLog', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
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
});
