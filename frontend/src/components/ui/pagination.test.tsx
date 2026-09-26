import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts ? `${key}:${JSON.stringify(opts)}` : key,
  }),
}));

import { TooltipProvider } from './tooltip';
import { Pagination } from './pagination';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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

  const button = (label: string) =>
    container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`);

  it('renders the page-size select only with pageSize', async () => {
    await render(<Pagination page={1} pageCount={3} onPageChange={vi.fn()} />);
    expect(container.querySelector('[data-slot="select-trigger"]')).toBeNull();
    await render(
      <Pagination
        page={1}
        pageCount={3}
        onPageChange={vi.fn()}
        pageSize={10}
        onPageSizeChange={vi.fn()}
      />,
    );
    expect(
      container.querySelector('[data-slot="select-trigger"]'),
    ).not.toBeNull();
  });

  it('pages with the four chevrons and disables at the ends', async () => {
    const onPageChange = vi.fn();
    await render(
      <Pagination page={1} pageCount={3} onPageChange={onPageChange} />,
    );
    expect(button('pagination.firstPage')!.disabled).toBe(true);
    expect(button('pagination.previousPage')!.disabled).toBe(true);
    await act(async () => button('pagination.nextPage')!.click());
    expect(onPageChange).toHaveBeenCalledWith(2);
    await act(async () => button('pagination.lastPage')!.click());
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it('puts the summary on the left and spreads the row', async () => {
    await render(
      <Pagination
        page={3}
        pageCount={41}
        onPageChange={vi.fn()}
        summary="1,024 users"
      />,
    );
    const row = container.firstElementChild as HTMLElement;
    expect(row.className).toContain('justify-between');
    expect(row.textContent).toContain('1,024 users');
  });

  it('swaps chevrons for two text buttons with labels="text"', async () => {
    await render(
      <Pagination
        page={2}
        pageCount={3}
        onPageChange={vi.fn()}
        labels="text"
      />,
    );
    expect(button('pagination.firstPage')).toBeNull();
    const texts = Array.from(container.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(texts).toEqual(['pagination.previousPage', 'pagination.nextPage']);
  });
});
