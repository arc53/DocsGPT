import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const connectors = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  listConnections: vi.fn(),
  getConnection: vi.fn(),
  disconnect: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: connectors }));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch: vi.fn(), modals: null }),
}));

const customModels = vi.hoisted(() => ({
  listCustomModels: vi.fn(),
  deleteCustomModel: vi.fn(),
}));
vi.mock('../api/services/customModelsService', () => ({
  default: customModels,
}));
vi.mock('../api/services/modelService', () => ({
  default: { getModels: vi.fn(), transformModels: vi.fn(() => []) },
}));
vi.mock('../modals/CustomModelModal', () => ({ default: () => null }));

import connectorsReducer from '../connectors/connectorsSlice';
import workspaceReducer, {
  PERSONAL_ROW,
  type WorkspaceRole,
} from '../workspace/workspaceSlice';
import Connectors from './Connectors';
import CustomModels from './CustomModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const workspaceState = (role?: WorkspaceRole) => ({
  current: role ? 't1' : 'personal',
  workspaces: role
    ? [
        PERSONAL_ROW,
        { id: 't1', kind: 'team' as const, name: 'Operations', role },
      ]
    : [PERSONAL_ROW],
  loaded: true,
  loading: false,
  epoch: 0,
  lastReason: null,
  latestRequestId: null,
});

const makeStore = (role?: WorkspaceRole) =>
  configureStore({
    reducer: {
      connectors: connectorsReducer,
      preference: (state = { token: 'tok' }) => state,
      workspace: workspaceReducer,
    },
    preloadedState: { workspace: workspaceState(role) },
  });

describe('Personal-only pages in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    Object.values(connectors).forEach((fn) => fn.mockReset());
    Object.values(customModels).forEach((fn) => fn.mockReset());
    connectors.getCatalog.mockResolvedValue({ success: true, connectors: [] });
    connectors.listConnections.mockResolvedValue({
      success: true,
      connections: [],
    });
    customModels.listCustomModels.mockResolvedValue([]);
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    page: 'connectors' | 'models',
    role?: WorkspaceRole,
  ) => {
    store = makeStore(role);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter
            initialEntries={[
              page === 'connectors'
                ? '/settings/connectors'
                : '/settings/custom-models',
            ]}
          >
            {page === 'connectors' ? <Connectors /> : <CustomModels />}
          </MemoryRouter>
        </Provider>,
      );
    });
  };
  const alert = () =>
    container.querySelector<HTMLElement>('[data-slot="alert"]');
  const switchButton = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === 'settings.connectors.personalOnly.switch',
    );

  it('Connectors in a team: says connections are personal, offers a switch and loads nothing', async () => {
    await render('connectors', 'admin');
    expect(alert()?.textContent).toContain(
      'settings.connectors.personalOnly.connections',
    );
    expect(connectors.getCatalog).not.toHaveBeenCalled();
    expect(connectors.listConnections).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid^="connector-card-"]')).toBe(
      null,
    );
    await act(async () => switchButton()!.click());
    expect(store.getState().workspace.current).toBe('personal');
  });

  it('Connectors in Personal: the catalog as before', async () => {
    await render('connectors');
    expect(switchButton()).toBeUndefined();
    expect(connectors.getCatalog).toHaveBeenCalled();
  });

  it('Custom models in a team: says models are personal and loads nothing', async () => {
    await render('models', 'editor');
    expect(alert()?.textContent).toContain(
      'settings.customModels.personalOnly',
    );
    expect(customModels.listCustomModels).not.toHaveBeenCalled();
    await act(async () => switchButton()!.click());
    expect(store.getState().workspace.current).toBe('personal');
  });

  it('Custom models in Personal: the list as before', async () => {
    await render('models');
    expect(switchButton()).toBeUndefined();
    expect(customModels.listCustomModels).toHaveBeenCalled();
  });
});
