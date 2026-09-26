import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { Pagination } from './pagination';
import { TooltipProvider } from './tooltip';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('Pagination page size', () => {
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

  const render = async (onRowsPerPageChange = vi.fn()) => {
    await act(async () => {
      root.render(
        <TooltipProvider>
          <Pagination
            page={1}
            pageCount={3}
            pageSize={10}
            onPageChange={vi.fn()}
            onPageSizeChange={onRowsPerPageChange}
          />
        </TooltipProvider>,
      );
    });
    return onRowsPerPageChange;
  };

  const trigger = () =>
    document.body.querySelector<HTMLButtonElement>(
      '[data-slot="select-trigger"]',
    );

  it('shows the current value in a labelled combobox trigger', async () => {
    await render();
    const el = trigger();
    expect(el).not.toBeNull();
    expect(el!.getAttribute('role')).toBe('combobox');
    expect(el!.getAttribute('aria-label')).toBe('pagination.rowsPerPage');
    expect(el!.getAttribute('data-size')).toBe('sm');
    expect(el!.textContent).toContain('10');
  });

  it('calls onRowsPerPageChange with the chosen number', async () => {
    const onChange = await render();
    const el = trigger()!;
    await act(async () => {
      el.dispatchEvent(
        new PointerEvent('pointerdown', {
          bubbles: true,
          button: 0,
          pointerType: 'mouse',
        }),
      );
    });
    const option = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="option"]'),
    ).find((o) => o.textContent === '50');
    expect(option).toBeDefined();
    await act(async () => option!.click());
    expect(onChange).toHaveBeenCalledWith(50);
  });

  it('labels the page buttons by their action', async () => {
    await render();
    const labels = Array.from(
      container.querySelectorAll<HTMLButtonElement>('button[aria-label]'),
    ).map((b) => b.getAttribute('aria-label'));
    expect(labels).toEqual(
      expect.arrayContaining([
        'pagination.firstPage',
        'pagination.previousPage',
        'pagination.nextPage',
        'pagination.lastPage',
      ]),
    );
    expect(container.querySelector('img')).toBeNull();
    // IconButton: the name is aria-label and the hint is a tooltip, never a
    // native title.
    expect(container.querySelector('button[title]')).toBeNull();
  });
});
