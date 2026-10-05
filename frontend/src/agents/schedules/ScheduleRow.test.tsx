import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));
vi.mock('./RunLog', () => ({ default: () => <div data-testid="runlog" /> }));

import ScheduleRow from './ScheduleRow';
import type { Schedule } from '../types/schedule';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const base: Schedule = {
  id: 's1',
  user_id: 'u',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Weekly compliance digest',
  instruction: 'Summarise expiring certificates.',
  status: 'active',
  cron: '0 9 * * 1',
  timezone: 'Europe/Berlin',
  next_run_at: '2026-09-28T07:00:00Z',
  last_run_at: '2026-09-21T07:00:00Z',
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 0,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
};

describe('ScheduleRow', () => {
  let container: HTMLDivElement;
  let root: Root;
  const handlers = {
    onToggleRuns: vi.fn(),
    onEdit: vi.fn(),
    onSetPaused: vi.fn(),
    onRunNow: vi.fn(),
    onDelete: vi.fn(),
    onSelectRun: vi.fn(),
  };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (schedule: Schedule, expanded = false) => {
    await act(async () => {
      root.render(
        <ScheduleRow schedule={schedule} expanded={expanded} {...handlers} />,
      );
    });
  };

  const buttons = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button'));

  it('is a subtle panel with one visible action and a menu', async () => {
    await render(base);
    const card = container.querySelector<HTMLElement>('[data-slot="card"]')!;
    expect(card.dataset.variant).toBe('subtle');
    const runNow = buttons().find((b) =>
      b.textContent?.includes('agents.schedules.runNow'),
    )!;
    expect(runNow.dataset.variant).toBe('outline');
    expect(runNow.dataset.size).toBe('sm');
    expect(runNow.dataset.shape).toBe('pill');
    // Edit, Pause and Delete live in the menu, not as pills.
    expect(
      buttons().some((b) => b.textContent === 'agents.schedules.edit'),
    ).toBe(false);
    expect(
      container.querySelector('[aria-label="agents.schedules.actions"]'),
    ).not.toBeNull();
    await act(async () => runNow.click());
    expect(handlers.onRunNow).toHaveBeenCalledWith(base);
  });

  it('reads its meta with icons, and shows the instruction under a name', async () => {
    await render(base);
    expect(container.textContent).toContain('Summarise expiring certificates.');
    expect(container.textContent).toContain('Europe/Berlin');
    expect(container.textContent).toContain('agents.schedules.meta.nextRun');
    expect(container.textContent).not.toContain('tz:');
    expect(container.querySelector('svg.lucide-repeat')).not.toBeNull();
  });

  it('offers Resume while paused and flags a failure streak', async () => {
    await render({ ...base, status: 'paused', consecutive_failure_count: 2 });
    expect(
      buttons().some((b) => b.textContent?.includes('agents.schedules.resume')),
    ).toBe(true);
    const streak = Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    ).find((b) => b.textContent?.includes('agents.schedules.failureStreak'))!;
    expect(streak.dataset.variant).toBe('destructive');
    expect(streak.textContent).toContain(':2');
  });

  it('toggles its runs with a chevron and shows them flush in the card', async () => {
    await render(base, true);
    const toggle = container.querySelector<HTMLButtonElement>(
      'button[aria-label="agents.schedules.hideRuns"]',
    )!;
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(container.querySelector('[data-testid="runlog"]')).not.toBeNull();
    await act(async () => toggle.click());
    expect(handlers.onToggleRuns).toHaveBeenCalledWith('s1');
  });

  it('shows a one-time task with its run time and only a menu', async () => {
    await render({
      ...base,
      trigger_type: 'once',
      cron: null,
      run_at: '2026-10-01T08:00:00Z',
    });
    expect(container.textContent).toContain('agents.schedules.meta.runsAt');
    expect(
      buttons().some((b) => b.textContent?.includes('agents.schedules.runNow')),
    ).toBe(false);
    expect(
      container.querySelector('button[aria-label="agents.schedules.showRuns"]'),
    ).toBeNull();
  });
});
