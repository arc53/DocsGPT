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
});
