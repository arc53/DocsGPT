import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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
