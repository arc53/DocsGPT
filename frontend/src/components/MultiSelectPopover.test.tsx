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
});
