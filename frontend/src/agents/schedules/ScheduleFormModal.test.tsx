import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import ScheduleFormModal from './ScheduleFormModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
          agentToolIds={[]}
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
