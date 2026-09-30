import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));

const schedules = [
  {
    id: 's1',
    agent_id: 'a1',
    trigger_type: 'recurring',
    name: 'Weekly digest',
    instruction: 'Summarise.',
    status: 'active',
    cron: '0 9 * * 1',
    timezone: 'Europe/Berlin',
    next_run_at: '2099-09-28T07:00:00Z',
    consecutive_failure_count: 0,
  },
  {
    id: 's2',
    agent_id: 'a1',
    trigger_type: 'recurring',
    name: 'Daily queue',
    instruction: 'Check.',
    status: 'paused',
    cron: '30 8 * * 1-5',
    timezone: 'Europe/Berlin',
    consecutive_failure_count: 2,
  },
];

vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      preference: { token: 't' },
      schedules: { byAgent: { a1: schedules }, runsBySchedule: {} },
    }),
  useDispatch: () => vi.fn(() => ({ unwrap: () => Promise.resolve() })),
}));
vi.mock('../../api/services/userService', () => ({
  default: {
    getAgent: () =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({ id: 'a1', name: 'Carrier FAQ', tools: [] }),
      }),
  },
}));
vi.mock('../../api/services/schedulesService', () => ({
  default: {
    statsForAgent: () =>
      Promise.resolve({
        days: 30,
        runs: 14,
        failed: 3,
        tokens: 48230,
        latest_failure: {
          scheduled_for: '2026-09-14T09:00:00Z',
          status: 'timeout',
          error_type: 'timeout',
        },
      }),
  },
}));
vi.mock('./ScheduleRow', () => ({
  default: ({ schedule }: { schedule: { id: string } }) => (
    <div data-testid={`row-${schedule.id}`} />
  ),
}));
vi.mock('./ScheduleFormModal', () => ({ default: () => null }));
vi.mock('./RunDetailDrawer', () => ({ default: () => null }));
vi.mock('../../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../../navigation/SectionPageHeader', () => ({
  CurrentSectionHeader: () => <h1>Schedules</h1>,
}));
vi.mock('../../navigation/SectionPills', () => ({ default: () => null }));

import SchedulesView from './SchedulesView';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('SchedulesView', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/agents/manage/schedules/a1']}>
          <Routes>
            <Route
              path="/agents/manage/schedules/:agentId"
              element={<SchedulesView />}
            />
          </Routes>
        </MemoryRouter>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  it('puts New schedule in the agent toolbar, with no second heading', async () => {
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.textContent).toContain('Carrier FAQ');
    const create = Array.from(toolbar.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('agents.schedules.newRecurring'),
    )!;
    expect(create.dataset.variant).toBe('default');
    expect(create.dataset.size).toBe('field');
    expect(create.dataset.shape).toBe('pill');
    expect(container.querySelectorAll('h1, h2')).toHaveLength(1);
  });

  it('shows the stat row as StatCards, failures in the destructive tone', async () => {
    const tiles = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="card"]'),
    );
    expect(tiles).toHaveLength(4);
    expect(container.textContent).toContain('agents.schedules.stats.active');
    expect(container.textContent).toContain('14');
    const failed = tiles.find((c) =>
      c.textContent?.includes('agents.schedules.stats.failed'),
    )!;
    expect(failed.dataset.tone).toBe('destructive');
    expect(failed.textContent).toContain('3');
  });

  it('switches Recurring and One-time with underline tabs', async () => {
    const tabs = Array.from(container.querySelectorAll('[role="tab"]'));
    expect(tabs.map((t) => t.textContent)).toEqual([
      'agents.schedules.recurring2',
      'agents.schedules.oneTime0',
    ]);
    expect(container.querySelector('[data-testid="row-s1"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="row-s2"]')).not.toBeNull();
  });

  it('shows an empty tab as an EmptyState with New schedule', async () => {
    const oneTime = Array.from(
      container.querySelectorAll<HTMLElement>('[role="tab"]'),
    )[1];
    await act(async () => {
      oneTime.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      oneTime.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      oneTime.click();
    });
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.textContent).toContain('agents.schedules.noOneTime');
    expect(empty.querySelector('button')?.textContent).toContain(
      'agents.schedules.newRecurring',
    );
  });
});
