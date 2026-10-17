import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { Combobox, type ComboboxOption } from './combobox';
import { FormField } from './form-field';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
  document.body.innerHTML = '';
});

const options: ComboboxOption[] = [
  { value: 'cs', label: 'Customer Support' },
  { value: 'po', label: 'People Ops' },
  { value: 'cr', label: 'Carrier Relations', hint: 'UTC+1' },
];

const render = async (element: React.ReactElement) => {
  await act(async () => root.render(element));
};

const trigger = () =>
  container.querySelector<HTMLButtonElement>('button[role="combobox"]')!;

const open = async () => {
  await act(async () => {
    trigger().dispatchEvent(
      new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
    );
    trigger().click();
  });
};

const items = () =>
  Array.from(
    document.body.querySelectorAll<HTMLElement>('[data-slot="command-item"]'),
  );

const item = (label: string) =>
  items().find((el) => el.textContent?.includes(label))!;

describe('Combobox trigger', () => {
  it('is a field-height combobox Button with one rotating ChevronDown', async () => {
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Choose a team"
      />,
    );
    const button = trigger();
    expect(button.dataset.variant).toBe('combobox');
    expect(button.dataset.size).toBe('field');
    expect(button.dataset.slot).toBe('combobox-trigger');
    expect(button.className.split(' ')).toEqual(
      expect.arrayContaining(['group', 'w-full', 'justify-between']),
    );
    const icons = button.querySelectorAll('svg');
    expect(icons).toHaveLength(1);
    // A direct child, so the Button's has-[>svg] padding applies.
    expect(icons[0].parentElement).toBe(button);
    const classes = icons[0].getAttribute('class')!.split(' ');
    expect(classes).toEqual(
      expect.arrayContaining([
        'lucide-chevron-down',
        'size-4',
        'opacity-50',
        'group-data-[state=open]:rotate-180',
      ]),
    );
    expect(button.hasAttribute('data-placeholder')).toBe(true);
    expect(button.textContent).toBe('Choose a team');
  });

  it('shows the picked option and its hint, or valueOption when unlisted', async () => {
    await render(
      <Combobox
        options={options}
        value="cr"
        onValueChange={() => undefined}
        placeholder="Choose a team"
      />,
    );
    expect(trigger().hasAttribute('data-placeholder')).toBe(false);
    expect(trigger().textContent).toBe('Carrier RelationsUTC+1');
    await render(
      <Combobox
        options={[]}
        value="gone"
        valueOption={{ value: 'gone', label: 'Unlisted team', hint: '3' }}
        onValueChange={() => undefined}
        placeholder="Choose a team"
      />,
    );
    expect(trigger().textContent).toBe('Unlisted team3');
    expect(trigger().querySelector('[title="Unlisted team"]')).not.toBeNull();
  });

  it('takes shape, width classes, a name and disabled', async () => {
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        shape="pill"
        className="w-52"
        aria-label="Team"
        disabled
      />,
    );
    expect(trigger().dataset.shape).toBe('pill');
    expect(trigger().className.split(' ')).toContain('w-52');
    expect(trigger().className.split(' ')).not.toContain('w-full');
    expect(trigger().getAttribute('aria-label')).toBe('Team');
    expect(trigger().disabled).toBe(true);
  });

  it('wires into a FormField: id, describedby, invalid and required', async () => {
    await render(
      <FormField
        label="Team"
        hint="Only teams without one"
        error="Required"
        required
      >
        <Combobox
          options={options}
          value={null}
          onValueChange={() => undefined}
          placeholder="Pick"
        />
      </FormField>,
    );
    const label = container.querySelector<HTMLLabelElement>(
      '[data-slot="form-field-label"]',
    )!;
    expect(trigger().id).toBeTruthy();
    expect(label.htmlFor).toBe(trigger().id);
    expect(trigger().getAttribute('aria-invalid')).toBe('true');
    expect(trigger().getAttribute('aria-required')).toBe('true');
    expect(trigger().getAttribute('aria-describedby')).toContain('-hint');
  });
});

describe('Combobox list', () => {
  it('opens a modal popover at least the trigger width, 18rem by default', async () => {
    const sibling = document.createElement('div');
    document.body.appendChild(sibling);
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const content = document.body.querySelector<HTMLElement>(
      '[data-slot="popover-content"]',
    )!;
    expect(content).not.toBeNull();
    expect(content.className.split(' ')).toEqual(
      expect.arrayContaining([
        'min-w-(--radix-popover-trigger-width)',
        'w-72',
        'p-0',
      ]),
    );
    // Modal: the rest of the page is hidden behind it.
    expect(sibling.getAttribute('aria-hidden')).toBe('true');
    expect(trigger().getAttribute('aria-expanded')).toBe('true');
  });

  it('marks the picked option checked and the rest not', async () => {
    await render(
      <Combobox
        options={options}
        value="po"
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    expect(items()).toHaveLength(3);
    expect(item('People Ops').dataset.checked).toBe('true');
    expect(item('Customer Support').dataset.checked).toBeUndefined();
    // No hand-drawn Check icon reserving a column.
    expect(item('People Ops').querySelector('svg')).toBeNull();
    // A hint sits at the row's end, muted.
    const hint = item('Carrier Relations').querySelector(
      '[data-slot="combobox-hint"]',
    )!;
    expect(hint.textContent).toBe('UTC+1');
    expect(hint.className).toContain('text-muted-foreground');
  });

  it('selects on click, reports the option and closes', async () => {
    const onValueChange = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={onValueChange}
        placeholder="Pick"
      />,
    );
    await open();
    await act(async () => item('People Ops').click());
    expect(onValueChange).toHaveBeenCalledWith('po', options[1]);
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).toBeNull();
    expect(trigger().getAttribute('aria-expanded')).toBe('false');
  });

  it('walks the list with the arrow keys and picks with Enter', async () => {
    const onValueChange = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={onValueChange}
        placeholder="Pick"
      />,
    );
    await open();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    const key = (k: string) =>
      act(async () => {
        input.dispatchEvent(
          new KeyboardEvent('keydown', { key: k, bubbles: true }),
        );
      });
    await key('ArrowDown');
    expect(item('People Ops').getAttribute('data-selected')).toBe('true');
    await key('Enter');
    expect(onValueChange).toHaveBeenCalledWith('po', options[1]);
  });

  it('filters by label by default', async () => {
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      setter.call(input, 'people');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(items().map((el) => el.textContent)).toEqual(['People Ops']);
  });

  it('hands server search to the caller with shouldFilter={false}', async () => {
    const onSearchChange = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        searchPlaceholder="Search teams…"
        emptyText="No team matches."
        shouldFilter={false}
        search="zzz"
        onSearchChange={onSearchChange}
      />,
    );
    await open();
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    expect(input.placeholder).toBe('Search teams…');
    expect(input.value).toBe('zzz');
    // Not filtered here: the caller's results are shown as given.
    expect(items()).toHaveLength(3);
    await act(async () => item('People Ops').click());
    // A pick clears the search for the next open.
    expect(onSearchChange).toHaveBeenLastCalledWith('');
  });

  it('shows the empty text when nothing is listed', async () => {
    await render(
      <Combobox
        options={[]}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        emptyText="Every team has an allowance."
      />,
    );
    await open();
    expect(
      document.body.querySelector('[data-slot="command-empty"]')?.textContent,
    ).toBe('Every team has an allowance.');
  });

  it('renders groups under their headings', async () => {
    await render(
      <Combobox
        groups={[
          { heading: 'Teams', options: options.slice(0, 1) },
          { heading: 'People', options: options.slice(1, 2) },
          { heading: 'Empty', options: [] },
        ]}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const headings = Array.from(
      document.body.querySelectorAll('[cmdk-group-heading]'),
    ).map((el) => el.textContent);
    expect(headings).toEqual(['Teams', 'People']);
  });

  it('renderItem replaces the row body, with the checked state', async () => {
    await render(
      <Combobox
        options={options}
        value="cs"
        onValueChange={() => undefined}
        placeholder="Pick"
        renderItem={(option, { checked }) => (
          <span data-testid={`row-${option.value}`}>
            {option.label}
            {checked ? ' (current)' : ''}
          </span>
        )}
      />,
    );
    await open();
    expect(
      document.body.querySelector('[data-testid="row-cs"]')?.textContent,
    ).toBe('Customer Support (current)');
    expect(
      document.body.querySelector('[data-testid="row-po"]')?.textContent,
    ).toBe('People Ops');
  });

  it('can be opened and closed by the caller', async () => {
    const onOpenChange = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        open
        onOpenChange={onOpenChange}
      />,
    );
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).not.toBeNull();
    await act(async () => item('People Ops').click());
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe('Combobox mode="add"', () => {
  it('always shows the placeholder and marks nothing', async () => {
    const onValueChange = vi.fn();
    await render(
      <Combobox
        mode="add"
        options={options}
        value="po"
        onValueChange={onValueChange}
        placeholder="Add people or teams…"
      />,
    );
    expect(trigger().textContent).toBe('Add people or teams…');
    expect(trigger().hasAttribute('data-placeholder')).toBe(true);
    await open();
    expect(items().some((el) => el.dataset.checked)).toBe(false);
    await act(async () => item('Customer Support').click());
    expect(onValueChange).toHaveBeenCalledWith('cs', options[0]);
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).toBeNull();
  });
});
