import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import PageNotFound from './PageNotFound';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('PageNotFound', () => {
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

  it('links home through a pill Button, with its focus ring', () => {
    act(() => {
      root.render(
        <MemoryRouter>
          <PageNotFound />
        </MemoryRouter>,
      );
    });
    const link = container.querySelector('a')!;
    expect(link.getAttribute('href')).toBe('/');
    expect(link.dataset.slot).toBe('button');
    expect(link.dataset.shape).toBe('pill');
    expect(link.className).toContain('focus-visible:ring-3');
  });
});
