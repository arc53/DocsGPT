import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import TimezoneCombobox, { getTimezoneOffsetLabel } from './TimezoneCombobox';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const zones = ['Asia/Dhaka', 'Asia/Dubai', 'Europe/Warsaw'];

describe('TimezoneCombobox', () => {
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
    document.body.innerHTML = '';
  });

  const render = (onChange = vi.fn()) => {
    act(() => {
      root.render(
        <TimezoneCombobox
          value="Asia/Dubai"
          options={zones}
          onChange={onChange}
          ariaLabel="Timezone"
        />,
      );
    });
    return onChange;
  };
  const trigger = () =>
    container.querySelector<HTMLButtonElement>('[role="combobox"]')!;
  const open = () =>
    act(() => {
      trigger().dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger().click();
    });
  const items = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    );

  it('is the shared Combobox with the offset beside the zone', () => {
    render();
    expect(trigger().dataset.slot).toBe('combobox-trigger');
    expect(trigger().getAttribute('aria-label')).toBe('Timezone');
    expect(trigger().querySelector('.lucide-chevron-down')).not.toBeNull();
    expect(trigger().querySelector('.lucide-chevrons-up-down')).toBeNull();
    expect(trigger().textContent).toBe(
      `Asia/Dubai${getTimezoneOffsetLabel('Asia/Dubai')}`,
    );
  });

  it('marks the zone with the checked tint, not a left Check icon', () => {
    render();
    open();
    expect(
      document.body.querySelector('[data-slot="popover-content"]')?.className,
    ).toContain('min-w-(--radix-popover-trigger-width)');
    const dubai = items().find((i) => i.textContent?.startsWith('Asia/Dubai'))!;
    expect(dubai.dataset.checked).toBe('true');
    expect(dubai.querySelector('.lucide-check')).toBeNull();
    expect(
      dubai.querySelector('[data-slot="combobox-hint"]')?.textContent,
    ).toBe(getTimezoneOffsetLabel('Asia/Dubai'));
  });

  it('filters with matchesTimezone and reports the pick', () => {
    const onChange = render();
    open();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    act(() => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, 'asia/d');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(items().map((i) => i.textContent?.split('UTC')[0])).toEqual([
      'Asia/Dhaka',
      'Asia/Dubai',
    ]);
    act(() => items()[0].click());
    expect(onChange).toHaveBeenCalledWith('Asia/Dhaka');
  });
});
