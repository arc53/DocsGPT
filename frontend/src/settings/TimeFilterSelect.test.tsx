import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import TimeFilterSelect from './TimeFilterSelect';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('TimeFilterSelect', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('is named, grows with its value, and opens a menu as wide as its longest window', async () => {
    act(() =>
      root.render(<TimeFilterSelect value="last_30_days" onChange={vi.fn()} />),
    );
    const trigger = container.querySelector<HTMLElement>(
      '[data-slot="select-trigger"]',
    )!;
    expect(trigger.getAttribute('aria-label')).toBe(
      'activity.history.periodFilter',
    );
    const classes = trigger.className.split(' ');
    expect(classes).toContain('min-w-[125px]');
    expect(classes.some((c) => /^w-\[/.test(c))).toBe(false);
    await act(async () => {
      trigger.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }),
      );
    });
    const menu = document.querySelector<HTMLElement>(
      '[data-slot="select-content"]',
    )!;
    expect(menu.className.split(' ')).toContain('w-auto');
  });
});
