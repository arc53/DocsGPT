import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import { LoadMoreStatus } from './load-more-status';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('LoadMoreStatus', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    root = createRoot(container);
  });
  afterEach(async () => {
    await act(async () => root.unmount());
  });

  const render = (
    props: Partial<React.ComponentProps<typeof LoadMoreStatus>>,
  ) =>
    act(async () =>
      root.render(
        <LoadMoreStatus
          loading={false}
          error={false}
          done={false}
          onRetry={vi.fn()}
          {...props}
        />,
      ),
    );
  const strip = () =>
    container.querySelector('[data-slot="load-more-status"]')!;

  it('keeps its height when idle, so the strip does not jump', async () => {
    await render({});
    expect(strip().className).toContain('h-9');
    expect(strip().textContent).toBe('');
  });

  it('announces loading, the end and a failure politely', async () => {
    await render({ loading: true });
    expect(strip().getAttribute('aria-live')).toBe('polite');
    expect(strip().textContent).toContain('pagination.loadingOlder');
    await render({ done: true });
    expect(strip().textContent).toBe('pagination.noOlder');
  });

  it('offers Retry after a failed page', async () => {
    const onRetry = vi.fn();
    await render({ error: true, onRetry });
    expect(strip().textContent).toContain('pagination.olderFailed');
    const retry = strip().querySelector('button')!;
    expect(retry.textContent).toBe('retry');
    await act(async () => retry.click());
    expect(onRetry).toHaveBeenCalled();
  });
});
