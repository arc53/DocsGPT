import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { Checkbox } from './checkbox';
import { FormField } from './form-field';

function render(element: React.ReactElement): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

describe('Checkbox', () => {
  it('is a 16px themed box with a 6px radius by default', () => {
    const box = render(<Checkbox aria-label="agents:read" />)
      .firstElementChild as HTMLElement;
    expect(box.getAttribute('role')).toBe('checkbox');
    expect(box.className).toContain('size-4');
    expect(box.className).toContain('rounded-sm');
    expect(box.className).toContain('border-input');
    expect(box.className).toContain('data-[state=checked]:bg-primary');
    expect(box.className).toContain('focus-visible:ring-3');
  });

  it('size="sm" is 14px with a 12px check', () => {
    const host = render(<Checkbox size="sm" checked aria-label="Filled" />);
    const box = host.firstElementChild as HTMLElement;
    expect(box.className).toContain('size-3.5');
    expect(box.className).not.toMatch(/(^|\s)size-4(\s|$)/);
    expect(host.querySelector('svg')?.getAttribute('class')).toContain(
      'size-3',
    );
  });

  it('shows the check only while checked', () => {
    expect(
      render(<Checkbox checked aria-label="a" />).querySelector('svg'),
    ).not.toBeNull();
    expect(
      render(<Checkbox checked={false} aria-label="a" />).querySelector('svg'),
    ).toBeNull();
  });

  // Both glyphs are drawn and the indicator's own state hides one, so an
  // uncontrolled box (defaultChecked, a form reset) shows the right one too.
  it.each([
    ['indeterminate', 'lucide-minus'],
    [true, 'lucide-check'],
  ] as const)('defaultChecked=%s shows only %s', (value, visible) => {
    const host = render(<Checkbox defaultChecked={value} aria-label="a" />);
    const indicator = host.querySelector('[data-slot="checkbox-indicator"]')!;
    const state = indicator.getAttribute('data-state');
    const shown = Array.from(host.querySelectorAll('svg')).filter(
      (svg) =>
        !(svg.getAttribute('class') ?? '').includes(
          `group-data-[state=${state}]:hidden`,
        ),
    );
    expect(shown).toHaveLength(1);
    expect(shown[0].getAttribute('class')).toContain(visible);
  });

  it('takes its id and invalid state from a FormField', () => {
    const host = render(
      <FormField label="Stream output to user" error="Required">
        <Checkbox />
      </FormField>,
    );
    const box = host.querySelector('[role="checkbox"]')!;
    expect(host.querySelector('label')!.getAttribute('for')).toBe(box.id);
    expect(box.getAttribute('aria-invalid')).toBe('true');
  });
});

describe('Checkbox tick colour', () => {
  it('keeps its own tick colour inside a parent that greys svgs', () => {
    const host = render(<Checkbox size="sm" checked aria-label="Picked" />);
    expect(host.querySelector('svg')?.getAttribute('class')).toContain(
      'text-current',
    );
  });
});
