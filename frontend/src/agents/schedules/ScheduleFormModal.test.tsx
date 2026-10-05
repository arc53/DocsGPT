import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// A plain input stands in for the time picker so a test can change the time.
vi.mock('@/components/ui/time-picker', () => ({
  TimePicker: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (next: string) => void;
  }) => (
    <input
      data-testid="time-picker"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));

import ScheduleFormModal from './ScheduleFormModal';
import type { Schedule } from '../types/schedule';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const approvalTools = [
  { id: 'github', name: 'GitHub' },
  { id: 'device', name: 'Build box' },
];

const saved = {
  id: 's1',
  agent_id: 'a1',
  trigger_type: 'recurring',
  name: 'Digest',
  instruction: 'Summarise.',
  status: 'active',
  cron: '0 9 * * *',
  timezone: 'UTC',
  tool_allowlist: ['device', 'safe-tool'],
  created_via: 'ui',
  consecutive_failure_count: 0,
} as unknown as Schedule;

describe('ScheduleFormModal tool approvals', () => {
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

  const render = async (
    onSubmit: (payload: unknown) => void,
    initial: Schedule | null = null,
    tools = approvalTools,
  ) => {
    await act(async () => {
      root.render(
        <ScheduleFormModal
          open
          initial={initial}
          approvalTools={tools}
          onClose={() => undefined}
          onSubmit={onSubmit}
        />,
      );
    });
  };

  const checkboxFor = (id: string) =>
    document.body.querySelector<HTMLButtonElement>(`#schedule-approve-${id}`);
  const submitButton = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'agents.schedules.modal.create');

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

  it('leaves tools that need approval unticked for a new schedule', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit);
    expect(checkboxFor('github')?.getAttribute('data-state')).toBe('unchecked');
    expect(checkboxFor('device')?.getAttribute('data-state')).toBe('unchecked');
    await typeInstruction('Check the queue.');
    await act(async () => submitButton()!.click());
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0].tool_allowlist).toEqual([]);
  });

  it('sends a tool once it is ticked, with the warning shown', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit);
    expect(document.body.textContent).toContain(
      'agents.schedules.modal.approvalTools.warning',
    );
    await act(async () => checkboxFor('github')!.click());
    await typeInstruction('Check the queue.');
    await act(async () => submitButton()!.click());
    expect(onSubmit.mock.calls[0][0].tool_allowlist).toEqual(['github']);
  });

  it('shows a saved schedule’s approvals and keeps entries it does not list', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit, saved);
    expect(checkboxFor('device')?.getAttribute('data-state')).toBe('checked');
    expect(checkboxFor('github')?.getAttribute('data-state')).toBe('unchecked');
    const save = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === 'agents.schedules.modal.save');
    await act(async () => save!.click());
    expect(onSubmit.mock.calls[0][0].tool_allowlist).toEqual([
      'safe-tool',
      'device',
    ]);
  });

  it('hides the section when no tool needs approval', async () => {
    await render(vi.fn(), null, []);
    expect(document.body.textContent).not.toContain(
      'agents.schedules.modal.approvalTools.label',
    );
  });
});

describe('ScheduleFormModal editing', () => {
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

  const inTwoDays = new Date(Date.now() + 2 * 24 * 3600 * 1000);
  const savedOnce = {
    ...saved,
    trigger_type: 'once',
    cron: null,
    run_at: inTwoDays.toISOString(),
    next_run_at: inTwoDays.toISOString(),
  } as unknown as Schedule;

  const render = async (
    onSubmit: (payload: unknown) => void | Promise<void>,
    initial: Schedule,
  ) => {
    await act(async () => {
      root.render(
        <ScheduleFormModal
          open
          initial={initial}
          approvalTools={[]}
          onClose={() => undefined}
          onSubmit={onSubmit}
        />,
      );
    });
  };
  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === text);

  const setTime = async (value: string) => {
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-testid="time-picker"]',
    )!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
  const currentTime = () =>
    document.body.querySelector<HTMLInputElement>(
      '[data-testid="time-picker"]',
    )!.value;

  it('leaves run_at out when the time is unchanged, even if it is near or past', async () => {
    const past = new Date(Date.now() - 2 * 60 * 1000).toISOString();
    const onSubmit = vi.fn();
    await render(onSubmit, {
      ...savedOnce,
      status: 'paused',
      run_at: past,
      next_run_at: null,
    } as unknown as Schedule);
    await act(async () => button('agents.schedules.modal.save')!.click());
    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).not.toHaveProperty('run_at');
    expect(document.body.textContent).not.toContain(
      'agents.schedules.modal.errors.runAtInPast',
    );
  });

  it('sends run_at when the time changed', async () => {
    const onSubmit = vi.fn();
    await render(onSubmit, savedOnce);
    await setTime(currentTime() === '11:30' ? '12:30' : '11:30');
    await act(async () => button('agents.schedules.modal.save')!.click());
    const payload = onSubmit.mock.calls[0][0];
    expect(payload.trigger_type).toBe('once');
    expect(typeof payload.run_at).toBe('string');
    expect(payload.run_at).not.toBe(savedOnce.run_at);
  });

  it('keeps a one-time task one-time and a recurring schedule recurring', async () => {
    await render(vi.fn(), savedOnce);
    expect(
      button('agents.schedules.modal.frequency.daily')!.hasAttribute(
        'disabled',
      ),
    ).toBe(true);
    expect(
      button('agents.schedules.modal.frequency.once')!.hasAttribute('disabled'),
    ).toBe(false);

    await render(vi.fn(), saved);
    expect(
      button('agents.schedules.modal.frequency.once')!.hasAttribute('disabled'),
    ).toBe(true);
    expect(
      button('agents.schedules.modal.frequency.weekly')!.hasAttribute(
        'disabled',
      ),
    ).toBe(false);
  });

  it('shows why the server refused the change', async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue(new Error("a completed task can't be rescheduled"));
    await render(onSubmit, savedOnce);
    await act(async () => button('agents.schedules.modal.save')!.click());
    const text = document.body.textContent ?? '';
    expect(text).toContain('agents.schedules.modal.errors.saveFailed');
    expect(text).toContain("a completed task can't be rescheduled");
  });

  it('reads the message of a serialized thunk error', async () => {
    const onSubmit = vi
      .fn()
      .mockRejectedValue({ name: 'Error', message: 'run_at is in the past.' });
    await render(onSubmit, savedOnce);
    await act(async () => button('agents.schedules.modal.save')!.click());
    expect(document.body.textContent).toContain('run_at is in the past.');
  });
});

describe('ScheduleFormModal pickers', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => {
      root.render(
        <ScheduleFormModal
          open
          approvalTools={[]}
          onClose={() => undefined}
          onSubmit={() => undefined}
        />,
      );
    });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const pickFrequency = (value: string) => {
    const item = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find(
      (b) => b.textContent === `agents.schedules.modal.frequency.${value}`,
    );
    expect(item).toBeTruthy();
    act(() => item!.click());
  };

  it('draws the date picker and timezone combobox at the field height', () => {
    pickFrequency('once');
    const combos = Array.from(
      document.body.querySelectorAll('[data-variant="combobox"]'),
    );
    // DatePicker + TimezoneCombobox.
    expect(combos.length).toBeGreaterThanOrEqual(2);
    for (const combo of combos) {
      expect(combo.getAttribute('data-size')).toBe('field');
    }
  });

  it('draws the yearly month and day selects at the field height', () => {
    pickFrequency('yearly');
    const triggers = Array.from(
      document.body.querySelectorAll('[data-slot="select-trigger"]'),
    );
    expect(triggers.length).toBeGreaterThanOrEqual(2);
    for (const trigger of triggers) {
      expect(trigger.getAttribute('data-size')).toBe('field');
    }
  });

  it('draws frequency and weekday as sm groups that fill their rows', () => {
    pickFrequency('weekly');
    const groups = Array.from(
      document.body.querySelectorAll('[data-slot="toggle-group"]'),
    );
    // Frequency, then the weekday picker.
    expect(groups).toHaveLength(2);
    for (const group of groups) {
      expect(group.className).toContain('bg-muted');
      expect(group.classList.contains('w-full')).toBe(true);
      expect(group.parentElement!.className).not.toContain('bg-muted');
      const items = Array.from(
        group.querySelectorAll('[data-slot="toggle-group-item"]'),
      );
      for (const item of items) {
        expect(item.className).toContain('flex-1');
        expect(item.className).toContain('h-8');
      }
    }
  });

  // A non-modal popover inside a Modal can't scroll or close on an outside
  // click (multi-select.tsx `modal`); a modal one hides the dialog behind it.
  it.each([
    ['the date picker', 'agents.schedules.modal.pickDate'],
    ['the timezone combobox', 'agents.schedules.modal.timezone'],
  ])('opens %s as a modal popover', (_name, label) => {
    pickFrequency('once');
    const trigger = document.body.querySelector<HTMLButtonElement>(
      `[data-variant="combobox"][aria-label="${label}"]`,
    );
    expect(trigger).not.toBeNull();
    act(() => trigger!.click());
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).not.toBeNull();
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.getAttribute('aria-hidden')).toBe('true');
  });
});
