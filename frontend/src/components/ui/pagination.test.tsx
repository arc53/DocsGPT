import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

import { TooltipProvider } from './tooltip';
import { Pagination, pageSlots } from './pagination';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('pageSlots', () => {
  it('lists every page up to five', () => {
    expect(pageSlots(1, 1)).toEqual([1]);
    expect(pageSlots(3, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  // Five slots from six pages on; an ellipsis always hides two pages or more.
  it.each([
    [1, 8, [1, 2, 3, 'ellipsis', 8]],
    [3, 8, [1, 2, 3, 'ellipsis', 8]],
    [4, 8, [1, 'ellipsis', 4, 'ellipsis', 8]],
    [5, 8, [1, 'ellipsis', 5, 'ellipsis', 8]],
    [6, 8, [1, 'ellipsis', 6, 7, 8]],
    [8, 8, [1, 'ellipsis', 6, 7, 8]],
    [3, 6, [1, 2, 3, 'ellipsis', 6]],
    [4, 6, [1, 'ellipsis', 4, 5, 6]],
  ])('page %i of %i', (page, count, expected) => {
    expect(pageSlots(page, count)).toEqual(expected);
  });
});

describe('Pagination', () => {
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
  });

  const render = async (node: React.ReactNode) => {
    await act(async () => {
      root.render(<TooltipProvider>{node}</TooltipProvider>);
    });
  };

  const full = () =>
    container.querySelector<HTMLElement>('[data-slot="pagination-full"]')!;
  const compact = () =>
    container.querySelector<HTMLElement>('[data-slot="pagination-compact"]')!;
  const numbers = () =>
    Array.from(full().querySelectorAll('button')).map((b) => b.textContent);

  it('draws nothing when every item fits on one page', async () => {
    await render(
      <Pagination page={1} pageSize={25} total={25} onPageChange={vi.fn()} />,
    );
    expect(container.querySelector('[data-slot="pagination"]')).toBeNull();
  });

  it('is a labelled nav with a numbered row and a compact row', async () => {
    await render(
      <Pagination page={1} pageSize={12} total={86} onPageChange={vi.fn()} />,
    );
    const nav = container.querySelector('[data-slot="pagination"]')!;
    expect(nav.tagName).toBe('NAV');
    expect(nav.getAttribute('aria-label')).toBe('pagination.label');
    // Compact below the pager's own 36rem, not the viewport's.
    expect(nav.className).toContain('@container');
    expect(full().className).toContain('@xl:flex');
    expect(compact().className).toContain('@xl:hidden');
  });

  it('numbers five slots and marks the current page', async () => {
    await render(
      <Pagination page={1} pageSize={12} total={86} onPageChange={vi.fn()} />,
    );
    // Previous and Next are icon-only, so their text is empty.
    expect(numbers()).toEqual(['', '1', '2', '3', '8', '']);
    expect(full().textContent).toContain('…');
    const current = full().querySelector('[aria-current="page"]')!;
    expect(current.textContent).toBe('1');
    expect(current.getAttribute('data-variant')).toBe('outline');
    expect(current.getAttribute('aria-label')).toBe(
      'pagination.goToPage:{"page":1}',
    );
  });

  it('goes to a numbered page, and to the neighbours', async () => {
    const onPageChange = vi.fn();
    await render(
      <Pagination
        page={4}
        pageSize={12}
        total={86}
        onPageChange={onPageChange}
      />,
    );
    const byLabel = (label: string) =>
      full().querySelector<HTMLButtonElement>(`[aria-label='${label}']`)!;
    await act(async () => byLabel('pagination.goToPage:{"page":8}').click());
    expect(onPageChange).toHaveBeenLastCalledWith(8);
    await act(async () => byLabel('pagination.previousPage').click());
    expect(onPageChange).toHaveBeenLastCalledWith(3);
    await act(async () => byLabel('pagination.nextPage').click());
    expect(onPageChange).toHaveBeenLastCalledWith(5);
  });

  it('disables Previous on the first page and Next on the last', async () => {
    await render(
      <Pagination page={8} pageSize={12} total={86} onPageChange={vi.fn()} />,
    );
    const nav = (row: HTMLElement, label: string) =>
      row.querySelector<HTMLButtonElement>(`[aria-label='${label}']`)!;
    expect(nav(full(), 'pagination.previousPage').disabled).toBe(false);
    expect(nav(full(), 'pagination.nextPage').disabled).toBe(true);
    expect(nav(compact(), 'pagination.nextPage').disabled).toBe(true);
  });

  it('summarises the range, with the list noun when given', async () => {
    await render(
      <Pagination
        page={2}
        pageSize={12}
        total={86}
        onPageChange={vi.fn()}
        rangeLabel={({ from, to, total }) =>
          `${from}-${to} of ${total} sources`
        }
      />,
    );
    expect(full().textContent).toContain('13-24 of 86 sources');
    // The compact row keeps the short, noun-free range and a page counter.
    expect(compact().textContent).toContain(
      'pagination.range:{"from":"13","to":"24","total":"86"}',
    );
    expect(compact().textContent).toContain('2 / 8');
  });

  it('ends the range at the total on the last page', async () => {
    await render(
      <Pagination page={8} pageSize={12} total={86} onPageChange={vi.fn()} />,
    );
    expect(full().textContent).toContain(
      'pagination.range:{"from":"85","to":"86","total":"86"}',
    );
  });

  // DESIGN.md: at a page size that fits everything the pager stays, so a
  // smaller size can be picked again; only the page buttons go.
  it('keeps the size select while the total exceeds the smallest option', async () => {
    await render(
      <Pagination
        page={1}
        pageSize={48}
        total={30}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(full().querySelector('[data-slot="select-trigger"]')).not.toBeNull();
    expect(full().querySelector('[aria-current="page"]')).toBeNull();
  });

  it('draws nothing with a select once the total fits the smallest option', async () => {
    await render(
      <Pagination
        page={1}
        pageSize={24}
        total={12}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(container.querySelector('[data-slot="pagination"]')).toBeNull();
  });

  it('shows the size select only with onPageSizeChange, and never compact', async () => {
    await render(
      <Pagination page={1} pageSize={25} total={100} onPageChange={vi.fn()} />,
    );
    expect(container.querySelector('[data-slot="select-trigger"]')).toBeNull();
    await render(
      <Pagination
        page={1}
        pageSize={12}
        total={100}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(full().querySelector('[data-slot="select-trigger"]')).not.toBeNull();
    expect(compact().querySelector('[data-slot="select-trigger"]')).toBeNull();
  });

  it('names the size select "Per page" unless pageSizeLabel says otherwise', async () => {
    await render(
      <Pagination
        page={1}
        pageSize={12}
        total={100}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(full().textContent).toContain('pagination.perPage');
    await render(
      <Pagination
        page={1}
        pageSize={10}
        pageSizeOptions={[10, 25]}
        total={100}
        onPageChange={vi.fn()}
        onPageSizeChange={vi.fn()}
        pageSizeLabel="Rows per page"
      />,
    );
    expect(full().textContent).toContain('Rows per page');
    expect(
      full()
        .querySelector('[data-slot="select-trigger"]')!
        .getAttribute('aria-label'),
    ).toBe('Rows per page');
  });
});
