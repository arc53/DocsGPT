import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('../hooks', () => ({
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
  useDarkTheme: () => [false, () => undefined],
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

import { MultiSelectPopover } from './MultiSelectPopover';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('MultiSelectPopover folder trails', () => {
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

  const rowsText = () =>
    Array.from(document.querySelectorAll('[data-slot="command-item"]')).map(
      (row) => row.textContent,
    );
  const type = (text: string) =>
    act(() => {
      const input = document.querySelector<HTMLInputElement>(
        '[data-slot="command-input"]',
      )!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  const show = (open = true) =>
    act(() => {
      root.render(
        <MultiSelectPopover
          open={open}
          trigger={<button type="button">Open</button>}
          items={[
            {
              id: 'a',
              label: 'Rate lookup',
              description: 'API tool',
              folderTrail: 'Carriers › Rates',
            },
            { id: 'b', label: 'Memory', description: 'Remembers' },
          ]}
          selectedIds={[]}
          onToggle={() => undefined}
        />,
      );
    });

  it("shows a row's folder only while a search is typed", () => {
    show();
    expect(rowsText()).toEqual(['Rate lookupAPI tool', 'MemoryRemembers']);
    type('rate');
    expect(rowsText()).toEqual(['Rate lookupCarriers › Rates · API tool']);
  });

  it("finds a row by its folder's name", () => {
    show();
    type('carriers');
    expect(rowsText()).toEqual(['Rate lookupCarriers › Rates · API tool']);
  });

  it('opens again with the search cleared', () => {
    show();
    type('carriers');
    show(false);
    show(true);
    expect(rowsText()).toHaveLength(2);
  });
});
