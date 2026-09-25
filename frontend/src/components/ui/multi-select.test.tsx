import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MultiSelect } from './multi-select';

const options = [
  { value: 'identity', label: 'Identity' },
  { value: 'access', label: 'Access' },
  { value: 'safety', label: 'Safety' },
];

function render(selected: string[]): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(
    <MultiSelect
      options={options}
      selected={selected}
      onChange={() => undefined}
      placeholder="All categories"
    />,
  );
  return host;
}

describe('MultiSelect', () => {
  it('uses the combobox trigger at the 42px form-row height', () => {
    const trigger = render([]).querySelector<HTMLElement>('[role="combobox"]')!;
    expect(trigger.dataset.slot).toBe('multi-select-trigger');
    expect(trigger.dataset.variant).toBe('combobox');
    expect(trigger.dataset.size).toBe('field');
    const classes = trigger.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['h-auto', 'min-h-10.5', 'py-1.5']),
    );
    // No restyle of another variant's surface.
    expect(classes).not.toContain('min-h-10');
    expect(classes).not.toContain('bg-background');
    expect(trigger.className).not.toContain('dark:bg-input/30');
  });

  it('marks the empty trigger as a placeholder', () => {
    const trigger = render([]).querySelector('[role="combobox"]')!;
    expect(trigger.hasAttribute('data-placeholder')).toBe(true);
    expect(trigger.textContent).toContain('All categories');
    const filled = render(['identity']).querySelector('[role="combobox"]')!;
    expect(filled.hasAttribute('data-placeholder')).toBe(false);
  });

  it('shows the first two picks as Badges and counts the rest', () => {
    const host = render(['identity', 'access', 'safety']);
    const chips = Array.from(host.querySelectorAll('[data-slot="badge"]'));
    expect(chips.map((chip) => chip.textContent)).toEqual([
      'Identity',
      'Access',
    ]);
    chips.forEach((chip) => {
      expect(chip.getAttribute('data-variant')).toBe('default');
      // The hand-rolled chip's heavier tint is gone.
      expect(chip.className.split(' ')).not.toContain('bg-primary/20');
    });
    expect(host.textContent).toContain('+1 more');
  });
});
