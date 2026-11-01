import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const media = vi.hoisted(() => ({ isMobile: false, isDesktop: true }));
vi.mock('../../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../hooks')>()),
  useMediaQuery: () => media,
}));

import PickerFooter from '../PickerFooter';
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
  media.isMobile = false;
  media.isDesktop = true;
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

describe('Combobox footer', () => {
  const footer = () =>
    document.body.querySelector<HTMLElement>('[data-slot="combobox-footer"]');

  it('pins the footer under the list, outside the scrolling list and cmdk', async () => {
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        footer={<button type="button">Add prompt</button>}
      />,
    );
    await open();
    const bar = footer()!;
    expect(bar).not.toBeNull();
    expect(bar.className.split(' ')).toEqual(
      expect.arrayContaining([
        'border-border',
        'shrink-0',
        'border-t',
        'px-4',
        'py-4',
      ]),
    );
    // Not inside the list, so it doesn't scroll away with the rows ...
    const list = document.body.querySelector('[data-slot="command-list"]')!;
    expect(list.contains(bar)).toBe(false);
    // ... and not inside cmdk's root, whose Enter handler would pick the
    // highlighted row instead of pressing the footer's button.
    expect(bar.closest('[cmdk-root]')).toBeNull();
    // After the list in DOM order, so Tab reaches it from the search box.
    const content = document.body.querySelector(
      '[data-slot="popover-content"]',
    )!;
    expect(content.contains(bar)).toBe(true);
    expect(
      list.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(bar.querySelector('button')!.tabIndex).toBe(0);
  });

  it('has no footer unless one is passed', async () => {
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    expect(footer()).toBeNull();
  });

  it('Enter on a footer button presses it and picks nothing', async () => {
    const onValueChange = vi.fn();
    const onAdd = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={onValueChange}
        placeholder="Pick"
        footer={
          <button type="button" onClick={onAdd}>
            Add prompt
          </button>
        }
      />,
    );
    await open();
    const button = footer()!.querySelector('button')!;
    await act(async () => {
      button.focus();
      const event = new KeyboardEvent('keydown', {
        key: 'Enter',
        bubbles: true,
        cancelable: true,
      });
      button.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    });
    expect(onValueChange).not.toHaveBeenCalled();
  });

  it('a render-function footer gets close(), which closes the popover', async () => {
    const onOpenChange = vi.fn();
    const onAdd = vi.fn();
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        onOpenChange={onOpenChange}
        placeholder="Pick"
        footer={({ close }) => (
          <button
            type="button"
            onClick={() => {
              close();
              onAdd();
            }}
          >
            Add prompt
          </button>
        )}
      />,
    );
    await open();
    await act(async () => footer()!.querySelector('button')!.click());
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).toBeNull();
  });

  it('takes PickerFooter: following its link navigates and closes the picker', async () => {
    const onAdd = vi.fn();
    await render(
      <MemoryRouter initialEntries={['/agents/new']}>
        <Routes>
          <Route
            path="/agents/new"
            element={
              <Combobox
                options={options}
                value={null}
                onValueChange={() => undefined}
                placeholder="Pick"
                footer={({ close }) => (
                  <PickerFooter
                    to="/settings/prompts"
                    linkLabel="Go to Prompts"
                    onNavigate={close}
                    actionLabel="Add prompt"
                    onAction={() => {
                      close();
                      onAdd();
                    }}
                  />
                )}
              />
            }
          />
          <Route path="/settings/prompts" element={<p>Prompts page</p>} />
        </Routes>
      </MemoryRouter>,
    );
    await open();
    const link = footer()!.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('/settings/prompts');
    await act(async () => link.click());
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).toBeNull();
    expect(container.textContent).toContain('Prompts page');
  });
});

describe('Combobox picker chrome', () => {
  const prompts: ComboboxOption[] = [
    {
      value: 'default',
      label: 'default',
      description: 'Answers from your documents and cites them.',
    },
    { value: 'strict', label: 'strict', description: 'Only your documents.' },
    { value: 'empty', label: 'Empty prompt' },
  ];

  const typeSearch = async (text: string) => {
    const input = document.body.querySelector<HTMLInputElement>(
      '[data-slot="command-input"]',
    )!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('has no title, filters or lines unless asked', async () => {
    await render(
      <Combobox
        options={options}
        value="po"
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const content = document.body.querySelector<HTMLElement>(
      '[data-slot="popover-content"]',
    )!;
    expect(content.querySelector('h3')).toBeNull();
    expect(content.querySelector('[data-slot="combobox-filters"]')).toBeNull();
    expect(
      content.querySelector('[data-slot="combobox-description"]'),
    ).toBeNull();
    expect(content.className).not.toContain('flex-col');
  });

  it('draws a title over the search, as the multi-pick pickers do', async () => {
    await render(
      <Combobox
        options={prompts}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
        title="Prompt"
      />,
    );
    await open();
    const content = document.body.querySelector<HTMLElement>(
      '[data-slot="popover-content"]',
    )!;
    const heading = content.querySelector('h3')!;
    expect(heading.textContent).toBe('Prompt');
    expect(heading.closest('[data-slot="section-header"]')).not.toBeNull();
    const input = content.querySelector('[data-slot="command-input"]')!;
    expect(
      heading.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // The pickers' height: up to 600px, the list scrolling inside.
    expect(content.className.split(' ')).toEqual(
      expect.arrayContaining([
        'flex',
        'flex-col',
        'overflow-hidden',
        'max-h-[min(600px,var(--radix-popover-content-available-height))]',
      ]),
    );
    const list = content.querySelector('[data-slot="command-list"]')!;
    expect(list.className).toContain('max-h-none');
  });

  it('draws filters under the search, whose keys never reach the list', async () => {
    const onValueChange = vi.fn();
    const onFilter = vi.fn();
    await render(
      <Combobox
        options={prompts}
        value={null}
        onValueChange={onValueChange}
        placeholder="Pick"
        filters={
          <button type="button" onClick={onFilter}>
            Included
          </button>
        }
      />,
    );
    await open();
    const strip = document.body.querySelector<HTMLElement>(
      '[data-slot="combobox-filters"]',
    )!;
    expect(strip).not.toBeNull();
    const input = document.body.querySelector('[data-slot="command-input"]')!;
    expect(
      input.compareDocumentPosition(strip) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      strip.compareDocumentPosition(
        document.body.querySelector('[data-slot="command-list"]')!,
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    const button = strip.querySelector('button')!;
    await act(async () => {
      button.focus();
      button.dispatchEvent(
        new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    expect(onValueChange).not.toHaveBeenCalled();
    await act(async () => button.click());
    expect(onFilter).toHaveBeenCalledTimes(1);
  });

  it("shows an option's description as a muted line, and searches it", async () => {
    await render(
      <Combobox
        options={prompts}
        value="strict"
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const line = item('default').querySelector<HTMLElement>(
      '[data-slot="combobox-description"]',
    )!;
    expect(line.textContent).toBe(
      'Answers from your documents and cites them.',
    );
    expect(line.className.split(' ')).toEqual(
      expect.arrayContaining(['text-muted-foreground', 'text-xs', 'truncate']),
    );
    // The trigger shows the label only.
    expect(trigger().textContent).toBe('strict');
    await typeSearch('answers');
    expect(items()).toHaveLength(1);
    expect(items()[0].dataset.value).toBe('default');
  });

  it('ends the picked row of a list with lines in a Check', async () => {
    await render(
      <Combobox
        options={prompts}
        value="strict"
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    const picked = item('strict');
    expect(picked.dataset.checked).toBe('true');
    const check = picked.querySelector('svg.lucide-check')!;
    expect(check).not.toBeNull();
    expect(check.getAttribute('class')).toContain('size-4');
    expect(picked.lastElementChild).toBe(check);
    expect(item('default').querySelector('svg')).toBeNull();
    // A row without a line keeps the list's label weight.
    expect(
      item('Empty prompt').querySelector('[title="Empty prompt"]')?.className,
    ).toContain('font-medium');
  });

  it('opens a bottom sheet with a handle and the title on a phone', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    const onValueChange = vi.fn();
    await render(
      <Combobox
        options={prompts}
        value={null}
        onValueChange={onValueChange}
        placeholder="Pick"
        title="Prompt"
        mobileSheet
        footer={<button type="button">Add prompt</button>}
      />,
    );
    await act(async () => trigger().click());
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).toBeNull();
    const sheet = document.body.querySelector<HTMLElement>(
      '[data-slot="sheet-content"]',
    )!;
    expect(sheet.dataset.side).toBe('bottom');
    expect(sheet.querySelector('[data-slot="sheet-handle"]')).not.toBeNull();
    expect(sheet.querySelector('h3')?.textContent).toBe('Prompt');
    expect(sheet.querySelector('[data-slot="combobox-footer"]')).not.toBeNull();
    // The search isn't focused, so the phone keyboard stays down.
    expect(document.activeElement?.getAttribute('data-slot')).not.toBe(
      'command-input',
    );
    await act(async () => item('strict').click());
    expect(onValueChange).toHaveBeenCalledWith('strict', prompts[1]);
    expect(
      document.body.querySelector('[data-slot="sheet-content"]'),
    ).toBeNull();
  });

  it('stays a popover on a phone without mobileSheet', async () => {
    media.isMobile = true;
    media.isDesktop = false;
    await render(
      <Combobox
        options={options}
        value={null}
        onValueChange={() => undefined}
        placeholder="Pick"
      />,
    );
    await open();
    expect(
      document.body.querySelector('[data-slot="popover-content"]'),
    ).not.toBeNull();
    expect(
      document.body.querySelector('[data-slot="sheet-content"]'),
    ).toBeNull();
  });
});
