import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { CapabilityChip } from './CustomModelModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CapabilityChip', () => {
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

  const render = (active: boolean, onClick = vi.fn()) => {
    act(() => {
      root.render(
        <CapabilityChip label="Tools" active={active} onClick={onClick} />,
      );
    });
    return container.querySelector<HTMLButtonElement>('button')!;
  };

  it('is a pressed toggle chip, secondary with a check when on', () => {
    const chip = render(true);
    // A toggle button named by its capability ("Tools, pressed"), not a
    // switch: the chip row reads as a set of on/off choices.
    expect(chip.dataset.slot).toBe('toggle-chip');
    expect(chip.hasAttribute('role')).toBe(false);
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.dataset.variant).toBe('secondary');
    expect(chip.dataset.size).toBe('sm');
    expect(chip.dataset.shape).toBe('pill');
    expect(chip.querySelector('svg')).not.toBeNull();
    expect(chip.className).not.toMatch(/success/);
  });

  it('uses the ghost-muted variant without a check when off', () => {
    const onClick = vi.fn();
    const chip = render(false, onClick);
    expect(chip.dataset.variant).toBe('ghost-muted');
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(chip.querySelector('svg')).toBeNull();
    expect(chip.textContent).toBe('Tools');
    act(() => chip.click());
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
