import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import {
  PICKER_FILTER_MIN_ITEMS,
  usePickerKindFilter,
} from './usePickerKindFilter';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type Row = { id: string; kind: 'a' | 'b' };
const KINDS = ['all', 'a', 'b'] as const;
const rowsOf = (a: number, b: number): Row[] => [
  ...Array.from({ length: a }, (_, i) => ({ id: `a${i}`, kind: 'a' as const })),
  ...Array.from({ length: b }, (_, i) => ({ id: `b${i}`, kind: 'b' as const })),
];

describe('usePickerKindFilter', () => {
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

  function Picker({ rows, open }: { rows: Row[]; open: boolean }) {
    const { items, filters } = usePickerKindFilter(rows, open, {
      kinds: KINDS,
      matches: (kind, row) => kind === 'all' || row.kind === kind,
      labelOf: (kind) => `kind.${kind}`,
      ariaLabel: 'Filter by kind',
    });
    return (
      <>
        <div data-testid="filters">{filters}</div>
        <p data-testid="count">{items.length}</p>
      </>
    );
  }

  const render = (rows: Row[], open = true) =>
    act(() => root.render(<Picker rows={rows} open={open} />));
  const filters = () =>
    container.querySelector('[data-testid="filters"]')!.innerHTML;
  const shown = () =>
    Number(container.querySelector('[data-testid="count"]')!.textContent);

  it('stays hidden while the list fits on one screen', () => {
    render(rowsOf(PICKER_FILTER_MIN_ITEMS - 4, 4));
    expect(filters()).toBe('');
    expect(shown()).toBe(PICKER_FILTER_MIN_ITEMS);
  });

  it('shows an xs track with counts past the threshold', () => {
    render(rowsOf(8, 3));
    const group = container.querySelector('[data-slot="toggle-group"]');
    expect(group?.getAttribute('aria-label')).toBe('Filter by kind');
    expect(
      Array.from(
        group!.querySelectorAll('[data-slot="toggle-group-item"]'),
      ).map((item) => item.textContent),
    ).toEqual(['kind.all11', 'kind.a8', 'kind.b3']);
  });

  it('stays hidden when no kind would narrow the list', () => {
    render(rowsOf(12, 0));
    expect(filters()).toBe('');
  });

  it('narrows to the picked kind and opens on All again', () => {
    render(rowsOf(8, 3));
    const b = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find((item) => item.textContent === 'kind.b3')!;
    act(() => b.click());
    expect(shown()).toBe(3);
    render(rowsOf(8, 3), false);
    render(rowsOf(8, 3), true);
    expect(shown()).toBe(11);
  });
});
