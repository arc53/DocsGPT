import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

import { MultiSelect } from './multi-select';

const options = [
  { value: 'identity', label: 'Identity' },
  { value: 'access', label: 'Access' },
  { value: 'safety', label: 'Safety' },
];

function render(selected: string[], shape?: 'default' | 'pill'): HTMLElement {
  const host = document.createElement('div');
  host.innerHTML = renderToStaticMarkup(
    <MultiSelect
      options={options}
      selected={selected}
      onChange={() => undefined}
      placeholder="All categories"
      shape={shape}
    />,
  );
  return host;
}

describe('MultiSelect', () => {
  it('reports the closed state through the Radix trigger', () => {
    // PopoverTrigger owns aria-expanded; the trigger doesn't set it by hand.
    const trigger = render([]).querySelector<HTMLElement>('[role="combobox"]')!;
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(trigger.getAttribute('aria-haspopup')).toBe('dialog');
  });

  it('uses the combobox trigger at the 38px form-row height', () => {
    const trigger = render([]).querySelector<HTMLElement>('[role="combobox"]')!;
    expect(trigger.dataset.slot).toBe('multi-select-trigger');
    expect(trigger.dataset.variant).toBe('combobox');
    expect(trigger.dataset.size).toBe('field');
    const classes = trigger.className.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining(['h-auto', 'min-h-9.5', 'py-1.5']),
    );
    // No restyle of another variant's surface.
    expect(classes).not.toContain('min-h-10');
    expect(classes).not.toContain('bg-background');
    expect(trigger.className).not.toContain('dark:bg-input/30');
  });

  it('is square by default and takes shape="pill" for page toolbars', () => {
    const square = render([]).querySelector<HTMLElement>('[role="combobox"]')!;
    expect(square.dataset.shape).toBe('default');
    expect(square.className.split(' ')).toContain('rounded-md');
    const pill = render([], 'pill').querySelector<HTMLElement>(
      '[role="combobox"]',
    )!;
    expect(pill.dataset.shape).toBe('pill');
    const classes = pill.className.split(' ');
    expect(classes).toContain('rounded-full');
    expect(classes).toContain('px-5');
    expect(classes).not.toContain('rounded-md');
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
    expect(host.textContent).toContain('components.multiSelect.more:1');
  });
});

describe('MultiSelect chips', () => {
  it('has no control nested in the trigger: no X, no role="button"', () => {
    const trigger = render(['identity', 'access']).querySelector(
      '[role="combobox"]',
    )!;
    expect(trigger.querySelector('[role="button"], button')).toBeNull();
    expect(trigger.querySelector('.lucide-x')).toBeNull();
  });

  it('shows one chip and "+N more" on a pill trigger, so a toolbar stays one row', () => {
    const host = render(['identity', 'access', 'safety'], 'pill');
    const chips = Array.from(host.querySelectorAll('[data-slot="badge"]'));
    expect(chips.map((chip) => chip.textContent)).toEqual(['Identity']);
    expect(host.textContent).toContain('components.multiSelect.more:2');
    const one = render(['identity'], 'pill');
    expect(one.querySelectorAll('[data-slot="badge"]')).toHaveLength(1);
    expect(one.textContent).not.toContain('components.multiSelect.more');
  });

  it('unselects from the list', async () => {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    const onChange = vi.fn();
    await act(async () =>
      root.render(
        <MultiSelect
          options={options}
          selected={['identity', 'access']}
          onChange={onChange}
        />,
      ),
    );
    const trigger = host.querySelector<HTMLElement>('[role="combobox"]')!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    const item = Array.from(
      document.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
    ).find((el) => el.textContent?.includes('Identity'))!;
    await act(async () => item.click());
    expect(onChange).toHaveBeenCalledWith(['access']);
    await act(async () => root.unmount());
    host.remove();
  });
});

describe('MultiSelect trigger chevron', () => {
  it("rotates SelectTrigger's ChevronDown when open", () => {
    const trigger = render([]).querySelector<HTMLElement>('[role="combobox"]')!;
    expect(trigger.className.split(' ')).toContain('group');
    const icon = trigger.querySelector('svg:last-child')!;
    const classes = icon.getAttribute('class')!.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'size-4',
        'opacity-50',
        'group-data-[state=open]:rotate-180',
      ]),
    );
    expect(icon.getAttribute('class')).toContain('lucide-chevron-down');
  });
});

describe('MultiSelect option description', () => {
  it('shows the description in the list only, never in the chips', async () => {
    const { act } = await import('react');
    const { createRoot } = await import('react-dom/client');
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement('div');
    document.body.appendChild(host);
    const root = createRoot(host);
    await act(async () =>
      root.render(
        <MultiSelect
          options={[
            { value: 'memory', label: 'Memory', description: 'Added by Lena' },
            { value: 'notes', label: 'Notes' },
          ]}
          selected={['memory']}
          onChange={() => undefined}
        />,
      ),
    );
    const trigger = host.querySelector<HTMLElement>('[role="combobox"]')!;
    expect(trigger.textContent).toContain('Memory');
    expect(trigger.textContent).not.toContain('Added by Lena');
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
    const item = Array.from(
      document.querySelectorAll('[data-slot="command-item"]'),
    ).find((el) => el.textContent?.includes('Memory'))!;
    expect(item.textContent).toContain('Added by Lena');
    await act(async () => root.unmount());
    host.remove();
  });
});
