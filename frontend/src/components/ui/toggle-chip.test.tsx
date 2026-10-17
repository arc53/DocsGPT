import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ToggleChip } from './toggle-chip';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('ToggleChip', () => {
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

  const render = (
    props: Partial<React.ComponentProps<typeof ToggleChip>> & {
      'data-testid'?: string;
    },
  ) => {
    act(() => {
      root.render(
        <ToggleChip pressed={false} {...props}>
          Tools
        </ToggleChip>,
      );
    });
    return container.querySelector<HTMLButtonElement>('button')!;
  };

  it('is a pressed toggle tinted secondary when on', () => {
    const chip = render({ pressed: true });
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.dataset.state).toBe('on');
    expect(chip.dataset.slot).toBe('toggle-chip');
    expect(chip.dataset.variant).toBe('secondary');
    expect(chip.className).toContain('bg-secondary');
    expect(chip.className).toContain('rounded-full');
    expect(chip.dataset.shape).toBe('pill');
    expect(chip.type).toBe('button');
  });

  it('is ghost-muted when off', () => {
    const chip = render({ pressed: false });
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(chip.dataset.variant).toBe('ghost-muted');
    expect(chip.className).toContain('text-muted-foreground');
    expect(chip.className).not.toContain('bg-secondary ');
  });

  it('defaults to xs with 10px pill padding, and takes sm', () => {
    const xs = render({});
    expect(xs.dataset.size).toBe('xs');
    expect(xs.className).toContain('h-7');
    expect(xs.className).toContain('px-2.5');
    expect(xs.className).not.toMatch(/(^|\s)px-2(\s|$)/);
    const sm = render({ size: 'sm' });
    expect(sm.dataset.size).toBe('sm');
    expect(sm.className).toContain('h-8');
  });

  it('reports the next state on click', () => {
    const onPressedChange = vi.fn();
    const chip = render({ pressed: false, onPressedChange });
    act(() => chip.click());
    expect(onPressedChange).toHaveBeenCalledWith(true);
  });

  it('keeps a locked chip on at full colour, with a lock, and never toggles', () => {
    const onPressedChange = vi.fn();
    const chip = render({ pressed: false, locked: true, onPressedChange });
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(chip.dataset.variant).toBe('secondary');
    expect(chip.getAttribute('aria-disabled')).toBe('true');
    // Not `disabled`: that fades it to opacity-50 and kills the title hover.
    expect(chip.disabled).toBe(false);
    expect(chip.dataset.locked).toBe('');
    const svg = chip.querySelector('svg');
    expect(svg).not.toBeNull();
    expect(svg?.getAttribute('class')).toContain('lucide-lock');
    expect(svg?.getAttribute('aria-hidden')).toBe('true');
    // The lock trails the label.
    expect(chip.lastElementChild).toBe(svg);
    expect(chip.textContent).toBe('Tools');
    // The lock doesn't shrink the xs pill's 10px sides or hover the tint.
    expect(chip.className).not.toContain('px-1.5');
    expect(chip.className).not.toContain('hover:bg-secondary/80');
    act(() => chip.click());
    expect(onPressedChange).not.toHaveBeenCalled();
  });

  it('fades and blocks a disabled chip', () => {
    const onPressedChange = vi.fn();
    const chip = render({ pressed: true, disabled: true, onPressedChange });
    expect(chip.disabled).toBe(true);
    expect(chip.className).toContain('disabled:opacity-50');
    act(() => chip.click());
    expect(onPressedChange).not.toHaveBeenCalled();
  });

  it('passes data-testid, title and onClick through', () => {
    const onClick = vi.fn();
    const chip = render({ 'data-testid': 'chip', title: 'Hint', onClick });
    expect(chip.dataset.testid).toBe('chip');
    expect(chip.title).toBe('Hint');
    act(() => chip.click());
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
