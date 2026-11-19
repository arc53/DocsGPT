import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      if (!options) return key;
      const values = Object.entries(options)
        .filter(([name]) => name !== 'interpolation')
        .map(([name, value]) => `${name}=${value}`)
        .join(',');
      return `${key}(${values})`;
    },
    i18n: { language: 'en' },
  }),
}));
vi.mock('./RunLog', () => ({ default: () => <div data-testid="runlog" /> }));
// The menu is a Radix dropdown; the tests only need its options.
vi.mock('../../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: { label: string; onClick: () => void }[];
  }) => (
    <div data-testid="menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

import type { PauseReason } from '../../payer/types';
import type { Schedule } from '../types/schedule';
import ScheduleRow from './ScheduleRow';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const TAKE_OVER = 'payer.common.takeOver.submit';

const base: Schedule = {
  id: 's1',
  user_id: 'u-dana',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Weekly lane report',
  instruction: 'Summarise lane volumes for the last seven days.',
  status: 'active',
  cron: '0 7 * * 1',
  timezone: 'Europe/Berlin',
  next_run_at: '2099-09-28T07:00:00Z',
  last_run_at: null,
  tool_allowlist: [],
  created_via: 'ui',
  consecutive_failure_count: 0,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
  paid_by: { user_id: 'u-dana', label: 'Dana' },
  paused_for: null,
  can_take_over: false,
};

describe('ScheduleRow payer', () => {
  let container: HTMLDivElement;
  let root: Root;
  const handlers = {
    onToggleRuns: vi.fn(),
    onEdit: vi.fn(),
    onSetPaused: vi.fn(),
    onRunNow: vi.fn(),
    onDelete: vi.fn(),
    onSelectRun: vi.fn(),
    onTakeOver: vi.fn(),
  };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    Object.values(handlers).forEach((handler) => handler.mockClear());
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    schedule: Schedule,
    extra: { viewerId?: string; teamName?: string } = {},
  ) => {
    await act(async () => {
      root.render(
        <ScheduleRow
          schedule={schedule}
          expanded={false}
          {...handlers}
          {...extra}
        />,
      );
    });
  };

  const text = () => container.textContent ?? '';
  const menu = () => container.querySelector('[data-testid="menu"]')!;
  const actionButtons = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).filter(
      (button) => !menu().contains(button),
    );
  const actionButton = (label: string) =>
    actionButtons().find((button) => button.textContent?.includes(label));
  const menuItem = (label: string) =>
    Array.from(menu().querySelectorAll('button')).find(
      (button) => button.textContent === label,
    );
  const statusBadge = () =>
    container.querySelector<HTMLElement>('[data-slot="badge"][data-status]')!;

  it('names who pays on the meta line, with a wallet', async () => {
    await render(base);
    expect(text()).toContain('payer.common.paidBy(name=Dana)');
    expect(container.querySelector('svg.lucide-wallet')).not.toBeNull();
  });

  it('says "Paid by you" when the reader pays', async () => {
    await render(base, { viewerId: 'u-dana' });
    expect(text()).toContain('payer.common.paidByYou');
    expect(text()).not.toContain('payer.common.paidBy(');
  });

  it('leaves the payer out when the server names nobody', async () => {
    await render({ ...base, paid_by: null });
    expect(text()).not.toContain('payer.common.paidBy');
    expect(container.querySelector('svg.lucide-wallet')).toBeNull();
  });

  it('names nobody when the team itself is the payer', async () => {
    // The team has no allowance, so a schedule it "pays" for has no payer.
    await render(
      {
        ...base,
        paid_by: { user_id: '__team__t1', label: 'Operations' },
        paused_for: { reason: 'no_payer', since: null },
      },
      { teamName: 'Operations' },
    );
    expect(text()).toContain('payer.common.pause.noPayer');
    expect(text()).not.toContain('payer.common.paidBy');
    expect(text()).not.toContain('Operations');
    expect(container.querySelector('svg.lucide-wallet')).toBeNull();
  });

  const reasons: [PauseReason, string][] = [
    ['owner_inactive', 'payer.common.pause.ownerInactive'],
    ['payer_left', 'payer.common.pause.payerLeft(name=Dana,team=Operations)'],
    ['no_payer', 'payer.common.pause.noPayer'],
    [
      'payer_out_of_allowance',
      'payer.common.pause.outOfAllowance(name=Dana,date=',
    ],
  ];

  it.each(reasons)(
    'shows a schedule paused for %s as Paused, with its reason',
    async (reason, sentence) => {
      await render(
        {
          ...base,
          paused_for: {
            reason,
            until:
              reason === 'payer_out_of_allowance'
                ? '2026-12-01T00:00:00Z'
                : null,
            since: null,
          },
        },
        { teamName: 'Operations' },
      );
      expect(statusBadge().dataset.status).toBe('paused');
      expect(statusBadge().dataset.variant).toBe('warning');
      expect(text()).toContain(sentence);
      const reasonLine = container.querySelector<HTMLElement>(
        '[data-pause-reason]',
      )!;
      expect(reasonLine.dataset.pauseReason).toBe(reason);
      expect(reasonLine.className).toContain('text-warning');
      // Its next run would be skipped, so it isn't promised.
      expect(text()).not.toContain('agents.schedules.meta.nextRun');
    },
  );

  it('adds since when its runs began to be skipped', async () => {
    await render({
      ...base,
      paused_for: { reason: 'no_payer', since: '2026-11-12T08:00:00Z' },
    });
    expect(text()).toContain(
      'payer.common.pause.withSince(reason=payer.common.pause.noPayer,date=',
    );
  });

  it('words the reader’s own allowance as theirs', async () => {
    await render(
      {
        ...base,
        paused_for: {
          reason: 'payer_out_of_allowance',
          until: '2026-12-01T00:00:00Z',
        },
      },
      { viewerId: 'u-dana' },
    );
    expect(text()).toContain('payer.common.pause.outOfAllowanceYou(date=');
  });

  it('makes Take over the button while paused for its payer', async () => {
    const schedule: Schedule = {
      ...base,
      paused_for: { reason: 'payer_left' },
      can_take_over: true,
    };
    await render(schedule);
    const takeOver = actionButton(TAKE_OVER)!;
    expect(takeOver).toBeDefined();
    expect(takeOver.dataset.variant).toBe('outline');
    expect(takeOver.querySelector('svg.lucide-wallet')).not.toBeNull();
    // A run now would be skipped too.
    expect(actionButton('agents.schedules.runNow')).toBeUndefined();
    expect(menuItem(TAKE_OVER)).toBeUndefined();
    await act(async () => takeOver.click());
    expect(handlers.onTakeOver).toHaveBeenCalledWith(schedule);
  });

  it('offers no Take over while paused when the server says no', async () => {
    await render({
      ...base,
      paused_for: { reason: 'payer_out_of_allowance' },
      can_take_over: false,
    });
    expect(actionButton(TAKE_OVER)).toBeUndefined();
    expect(menuItem(TAKE_OVER)).toBeUndefined();
    expect(actionButton('agents.schedules.runNow')).toBeUndefined();
  });

  it('keeps Take over in the menu of a running schedule', async () => {
    const schedule: Schedule = { ...base, can_take_over: true };
    await render(schedule);
    expect(actionButton('agents.schedules.runNow')).toBeDefined();
    expect(actionButton(TAKE_OVER)).toBeUndefined();
    const labels = Array.from(menu().querySelectorAll('button')).map(
      (button) => button.textContent,
    );
    expect(labels).toEqual([
      'agents.schedules.edit',
      'agents.schedules.pause',
      TAKE_OVER,
      'agents.schedules.delete',
    ]);
    await act(async () => menuItem(TAKE_OVER)!.click());
    expect(handlers.onTakeOver).toHaveBeenCalledWith(schedule);
  });

  it('keeps Take over in the menu of a schedule someone paused', async () => {
    await render({ ...base, status: 'paused', can_take_over: true });
    expect(actionButton('agents.schedules.resume')).toBeDefined();
    expect(menuItem(TAKE_OVER)).toBeDefined();
  });

  it('offers no Take over to a Viewer or to the payer', async () => {
    await render({ ...base, can_take_over: false });
    expect(menuItem(TAKE_OVER)).toBeUndefined();
    expect(actionButton(TAKE_OVER)).toBeUndefined();
    await render({ ...base, can_take_over: undefined });
    expect(menuItem(TAKE_OVER)).toBeUndefined();
  });

  it('offers no Take over when the page has no way to do it', async () => {
    await act(async () => {
      root.render(
        <ScheduleRow
          schedule={{ ...base, can_take_over: true }}
          expanded={false}
          {...handlers}
          onTakeOver={undefined}
        />,
      );
    });
    expect(menuItem(TAKE_OVER)).toBeUndefined();
  });

  it('shows a paused schedule a person stopped as before', async () => {
    // The server reports a payer pause only on an active schedule.
    await render({ ...base, status: 'paused' });
    expect(container.querySelector('[data-pause-reason]')).toBeNull();
    expect(actionButton('agents.schedules.resume')).toBeDefined();
  });
});
