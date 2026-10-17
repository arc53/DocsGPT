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
// The open confirm's submit; the test reads what handleSubmit returns.
const confirmProps: { current: Record<string, unknown> | null } = {
  current: null,
};
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: Record<string, unknown>) => {
    confirmProps.current = props;
    return null;
  },
}));
// Render the ⋯ menu's options inline so tests can click them.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: Array<{ label: string; onClick: () => void }>;
  }) => (
    <div data-testid="model-menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));

const listCustomModels = vi.fn();
const deleteCustomModel = vi.fn();
vi.mock('../api/services/customModelsService', () => ({
  default: {
    listCustomModels: (...args: unknown[]) => listCustomModels(...args),
    deleteCustomModel: (...args: unknown[]) => deleteCustomModel(...args),
  },
}));

import CustomModels from './CustomModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

describe('CustomModels', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    listCustomModels.mockReset();
    deleteCustomModel.mockReset();
    confirmProps.current = null;
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

  const MODEL = {
    id: 'm1',
    display_name: 'Llama 3.3 70B',
    upstream_model_id: 'llama-3.3-70b',
    base_url: 'https://api.together.xyz/v1',
    enabled: true,
  };

  const openDelete = async () => {
    listCustomModels.mockResolvedValue([MODEL]);
    await render();
    const del = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-testid="model-menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.customModels.actions.delete')!;
    await act(async () => del.click());
    expect(confirmProps.current?.modalState).toBe('ACTIVE');
  };

  it('a failed delete rejects so the confirm stays open, and keeps the card', async () => {
    deleteCustomModel.mockRejectedValue(new Error('Request failed (500)'));
    await openDelete();
    const submit = confirmProps.current!.handleSubmit as () => unknown;
    let result: unknown;
    await act(async () => {
      result = submit();
      await (result as Promise<unknown>).catch(() => undefined);
    });
    expect(result).toBeInstanceOf(Promise);
    await expect(result as Promise<unknown>).rejects.toThrow();
    expect(deleteCustomModel).toHaveBeenCalledWith('m1', 'token');
    // The dialog is left to ConfirmationModal: still open, still named.
    expect(confirmProps.current?.modalState).toBe('ACTIVE');
    expect(container.textContent).toContain('Llama 3.3 70B');
  });

  it('a successful delete resolves and drops the card', async () => {
    deleteCustomModel.mockResolvedValue(undefined);
    await openDelete();
    const submit = confirmProps.current!.handleSubmit as () => unknown;
    await act(async () => {
      await submit();
    });
    expect(container.textContent).not.toContain('Llama 3.3 70B');
  });
});
