import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const media = { isMobile: false, isDesktop: true };
vi.mock('../hooks', () => ({
  useMediaQuery: () => media,
  useDarkTheme: () => [false, () => undefined],
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

import { MultiSelectPopover } from './MultiSelectPopover';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const items = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
];

describe('MultiSelectPopover', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    media.isMobile = false;
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = () =>
    act(() => {
      root.render(
        <MultiSelectPopover
          open
          trigger={<button type="button">Open</button>}
          items={items}
          selectedIds={['b']}
          onToggle={() => undefined}
          className="max-h-40"
        />,
      );
    });

  it('puts className on the desktop popover', () => {
    render();
    const content = document.querySelector('[data-slot="popover-content"]');
    expect(content?.className).toContain('max-h-40');
  });

  it('caps the desktop popover at the room Radix reports, not the viewport', () => {
    // Opening upward from a low trigger, 80dvh pushed the title off-screen.
    act(() => {
      root.render(
        <MultiSelectPopover
          open
          trigger={<button type="button">Open</button>}
          items={items}
          selectedIds={[]}
          onToggle={() => undefined}
        />,
      );
    });
    const content = document.querySelector('[data-slot="popover-content"]');
    expect(content?.className).toContain(
      'max-h-[min(600px,var(--radix-popover-content-available-height))]',
    );
  });

  it('puts className on the mobile sheet', () => {
    media.isMobile = true;
    render();
    const content = document.querySelector('[data-slot="sheet-content"]');
    expect(content?.className).toContain('max-h-40');
  });

  it('uses the shared bottom-sheet shape and handle on phones', () => {
    media.isMobile = true;
    render();
    const content = document.querySelector('[data-slot="sheet-content"]')!;
    expect(content.querySelectorAll('[data-slot="sheet-handle"]')).toHaveLength(
      1,
    );
    expect(content.className).toContain('rounded-t-2xl');
    expect(content.className).not.toContain('env(');
    expect(content.className).not.toContain('dark:bg-card');
  });

  it('marks chosen rows with CommandItem checked and a primary tick', () => {
    render();
    const rows = document.querySelectorAll('[data-slot="command-item"]');
    expect(rows).toHaveLength(2);
    expect(rows[0].hasAttribute('data-checked')).toBe(false);
    expect(rows[1].getAttribute('data-checked')).toBe('true');
    rows.forEach((row) => expect(row.querySelector('img')).toBeNull());
    const tick = rows[1].querySelector('svg');
    expect(tick).not.toBeNull();
    expect(tick?.getAttribute('class')).toContain('text-primary');
    expect(rows[0].querySelector('svg')).toBeNull();
  });

  it("leaves aria-selected to cmdk's highlight, not the chosen state", () => {
    render();
    const rows = document.querySelectorAll('[data-slot="command-item"]');
    // cmdk highlights the first row; the chosen row is data-checked only.
    expect(rows[0].getAttribute('aria-selected')).toBe('true');
    expect(rows[1].getAttribute('aria-selected')).toBe('false');
  });

  it('lets Radix announce the open state on the trigger', () => {
    render();
    const trigger = container.querySelector('button');
    expect(trigger?.getAttribute('aria-expanded')).toBe('true');
  });

  it('runs the stock search strip edge to edge over an unframed list', () => {
    act(() => {
      root.render(
        <MultiSelectPopover
          open
          title="Pick"
          trigger={<button type="button">Open</button>}
          items={items}
          selectedIds={[]}
          onToggle={() => undefined}
        />,
      );
    });
    const strip = document.querySelector(
      '[data-slot="command-input-wrapper"]',
    )!;
    expect(strip.getAttribute('data-variant')).toBe('default');
    expect(strip.parentElement?.className).not.toMatch(/\bpx-4\b/);
    expect(
      strip.querySelector('[data-slot="command-input"]')?.className,
    ).not.toContain('h-10');
    const list = document.querySelector('[data-slot="command-list"]')!;
    expect(list.parentElement?.className ?? '').not.toContain('rounded-md');
    expect(list.parentElement?.className ?? '').not.toMatch(/\bborder\b/);
  });

  describe('footer', () => {
    const footer = () =>
      document.querySelector<HTMLElement>('[data-slot="multi-select-footer"]');

    const renderWithFooter = (onToggle = vi.fn(), onAdd = vi.fn()) =>
      act(() => {
        root.render(
          <MultiSelectPopover
            open
            trigger={<button type="button">Open</button>}
            items={items}
            selectedIds={[]}
            onToggle={onToggle}
            footer={
              <button type="button" onClick={onAdd}>
                Add tool
              </button>
            }
          />,
        );
      });

    it.each([
      ['the popover', false],
      ['the phone sheet', true],
    ])('pins it under the list in %s, outside cmdk', (_where, mobile) => {
      media.isMobile = mobile;
      renderWithFooter();
      const bar = footer()!;
      expect(bar.className.split(' ')).toEqual(
        expect.arrayContaining([
          'border-border',
          'shrink-0',
          'border-t',
          'px-4',
          'py-4',
        ]),
      );
      // Not in cmdk's root, whose Enter handler toggles the highlighted row.
      expect(bar.closest('[cmdk-root]')).toBeNull();
      const list = document.querySelector('[data-slot="command-list"]')!;
      expect(list.contains(bar)).toBe(false);
      // After the list, so Tab reaches it from the search box.
      expect(
        list.compareDocumentPosition(bar) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      const surface = document.querySelector(
        mobile
          ? '[data-slot="sheet-content"]'
          : '[data-slot="popover-content"]',
      )!;
      expect(surface.contains(bar)).toBe(true);
    });

    it('Enter on a footer button presses it and toggles no row', () => {
      const onToggle = vi.fn();
      renderWithFooter(onToggle);
      const button = footer()!.querySelector('button')!;
      act(() => {
        button.focus();
        const event = new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        });
        button.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
      });
      expect(onToggle).not.toHaveBeenCalled();
    });
  });

  describe('filters', () => {
    const renderWithFilters = (onToggle = vi.fn()) =>
      act(() => {
        root.render(
          <MultiSelectPopover
            open
            trigger={<button type="button">Open</button>}
            items={items}
            selectedIds={[]}
            onToggle={onToggle}
            filters={<button type="button">Websites</button>}
          />,
        );
      });

    const strip = () =>
      document.querySelector<HTMLElement>('[data-slot="multi-select-filters"]');

    it('draws the filter row between the search and the list', () => {
      renderWithFilters();
      const row = strip()!;
      const input = document.querySelector('[data-slot="command-input"]')!;
      const list = document.querySelector('[data-slot="command-list"]')!;
      expect(
        input.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(
        row.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      expect(row.className.split(' ')).toEqual(
        expect.arrayContaining(['px-3', 'pt-2', 'pb-1']),
      );
    });

    it('keeps its keys from cmdk: Enter presses a filter, not the row', () => {
      const onToggle = vi.fn();
      renderWithFilters(onToggle);
      const button = strip()!.querySelector('button')!;
      act(() => {
        button.focus();
        const event = new KeyboardEvent('keydown', {
          key: 'Enter',
          bubbles: true,
          cancelable: true,
        });
        button.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
      });
      expect(onToggle).not.toHaveBeenCalled();
    });

    it('draws no row without filters', () => {
      render();
      expect(strip()).toBeNull();
    });
  });

  describe('selectedFirst', () => {
    const grouped = [
      { id: 'a', label: 'Alpha', group: 'one' },
      { id: 'b', label: 'Beta', group: 'one' },
      { id: 'c', label: 'Gamma', group: 'two' },
    ];

    const renderPicker = (
      open: boolean,
      selectedIds: string[],
      extra: Record<string, unknown> = {},
    ) =>
      act(() => {
        root.render(
          <MultiSelectPopover
            open={open}
            trigger={<button type="button">Open</button>}
            items={grouped}
            selectedIds={selectedIds}
            onToggle={() => undefined}
            selectedFirst
            {...extra}
          />,
        );
      });

    const layout = () =>
      Array.from(document.querySelectorAll('[cmdk-group]')).map((group) => [
        group.querySelector('[cmdk-group-heading]')?.textContent ?? null,
        Array.from(group.querySelectorAll('[data-slot="command-item"]')).map(
          (row) => row.textContent,
        ),
      ]);

    it('lists what is chosen when it opens in a Selected group on top', () => {
      renderPicker(true, ['c']);
      expect(layout()).toEqual([
        ['Selected', ['Gamma']],
        ['one', ['Alpha', 'Beta']],
      ]);
    });

    it('keeps the rows still while toggling, and re-sorts on the next open', () => {
      renderPicker(true, ['c']);
      // Unticking Gamma and ticking Beta moves nothing.
      renderPicker(true, ['b']);
      expect(layout()).toEqual([
        ['Selected', ['Gamma']],
        ['one', ['Alpha', 'Beta']],
      ]);
      const gamma = document.querySelectorAll('[data-slot="command-item"]')[0];
      expect(gamma.hasAttribute('data-checked')).toBe(false);
      renderPicker(false, ['b']);
      renderPicker(true, ['b']);
      expect(layout()).toEqual([
        ['Selected', ['Beta']],
        ['one', ['Alpha']],
        ['two', ['Gamma']],
      ]);
    });

    it('draws no Selected group while nothing is chosen', () => {
      renderPicker(true, []);
      expect(layout().map(([heading]) => heading)).toEqual(['one', 'two']);
    });

    it('draws a group heading node in place of the group key', () => {
      act(() => {
        root.render(
          <MultiSelectPopover
            open
            trigger={<button type="button">Open</button>}
            items={[
              {
                id: 'a',
                label: 'Alpha',
                group: 'service:x',
                groupHeading: <span data-testid="heading">X service</span>,
              },
              { id: 'b', label: 'Beta', group: 'other' },
            ]}
            selectedIds={[]}
            onToggle={() => undefined}
          />,
        );
      });
      expect(document.querySelector('[data-testid="heading"]')).not.toBeNull();
      expect(layout().map(([heading]) => heading)).toEqual([
        'X service',
        'other',
      ]);
    });

    it('with loneGroupHeading off, heads a lone group only beside Selected', () => {
      const lone = [
        { id: 'a', label: 'Alpha', group: 'one' },
        { id: 'b', label: 'Beta', group: 'one' },
      ];
      act(() => {
        root.render(
          <MultiSelectPopover
            open
            trigger={<button type="button">Open</button>}
            items={lone}
            selectedIds={[]}
            onToggle={() => undefined}
            selectedFirst
            loneGroupHeading={false}
          />,
        );
      });
      expect(layout()).toEqual([[null, ['Alpha', 'Beta']]]);
      act(() => root.render(<></>));
      act(() => {
        root.render(
          <MultiSelectPopover
            open
            trigger={<button type="button">Open</button>}
            items={lone}
            selectedIds={['b']}
            onToggle={() => undefined}
            selectedFirst
            loneGroupHeading={false}
          />,
        );
      });
      expect(layout()).toEqual([
        ['Selected', ['Beta']],
        ['one', ['Alpha']],
      ]);
    });
  });
});
