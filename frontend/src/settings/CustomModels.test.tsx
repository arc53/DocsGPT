import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-redux', () => ({
  useSelector: () => 'token',
  useDispatch: () => vi.fn(),
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useLoaderState: (initial: boolean) => useState(initial),
}));

vi.mock('../modals/CustomModelModal', () => ({ default: () => null }));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));

const listCustomModels = vi.fn();
vi.mock('../api/services/customModelsService', () => ({
  default: {
    listCustomModels: (...args: unknown[]) => listCustomModels(...args),
  },
}));

import CustomModels from './CustomModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CustomModels', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listCustomModels.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = () =>
    act(async () => {
      root.render(
        <MemoryRouter>
          <CustomModels />
        </MemoryRouter>,
      );
    });

  const errorState = () =>
    container.querySelector<HTMLElement>(
      '[data-slot="empty-state"][data-tone="destructive"]',
    );

  it('shows a failed load as an error with Retry, not "no models yet"', async () => {
    listCustomModels.mockRejectedValue(new Error('down'));
    await render();
    const state = errorState()!;
    expect(state).not.toBeNull();
    expect(state.textContent).toContain('settings.customModels.loadError');
    expect(container.textContent).not.toContain('settings.customModels.empty');

    listCustomModels.mockResolvedValue([]);
    const retry = Array.from(state.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(listCustomModels).toHaveBeenCalledTimes(2);
    expect(errorState()).toBeNull();
    expect(container.textContent).toContain('settings.customModels.empty');
  });
});
