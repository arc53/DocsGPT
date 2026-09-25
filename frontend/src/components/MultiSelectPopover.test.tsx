import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const media = { isMobile: false, isTablet: false, isDesktop: true };
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
});
