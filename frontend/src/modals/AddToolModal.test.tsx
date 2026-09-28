import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getAvailableTools: vi.fn(async () => ({
      json: async () => ({
        data: [
          {
            name: 'memory',
            displayName: 'Memory',
            description: 'Remembers',
            configRequirements: {},
            actions: [],
            group: 'built_in',
          },
        ],
      }),
    })),
  },
}));

vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: vi.fn(async () => ({
      success: true,
      connectors: server.catalog,
    })),
    listConnections: vi.fn(async () => ({ success: true, connections: [] })),
  },
}));

const launch = vi.hoisted(() => vi.fn());
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import AddToolModal from './AddToolModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const entry = (overrides: Record<string, unknown>) => ({
  description: '',
  category: 'dev',
  publisher: 'built_in',
  capabilities: ['read', 'write'],
  available: true,
  connection_count: 0,
  connected_count: 0,
  state: 'available',
  ...overrides,
});

const server = vi.hoisted(() => ({ catalog: [] as unknown[] }));

describe('AddToolModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    launch.mockClear();
    server.catalog = [
      entry({
        key: 'mcp:notion',
        name: 'Notion',
        icon: 'notion',
        publisher: 'preset',
      }),
      entry({
        key: 'telegram',
        name: 'Telegram',
        icon: 'tool_telegram',
        connection_count: 1,
        connected_count: 1,
        state: 'connected',
      }),
      entry({
        key: 'google_drive',
        name: 'Google Drive',
        icon: 'drive',
        capabilities: ['sync'],
      }),
      entry({
        key: 'custom_mcp',
        name: 'MCP server',
        icon: 'mcp',
        publisher: 'custom',
      }),
    ];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    const setModalState = vi.fn();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/settings/tools']}>
            <Routes>
              <Route
                path="/settings/tools"
                element={
                  <AddToolModal
                    message=""
                    modalState="ACTIVE"
                    setModalState={setModalState}
                    getUserTools={vi.fn()}
                    onToolAdded={vi.fn()}
                  />
                }
              />
              <Route path="/settings/connectors" element={<div>DRAWER</div>} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    // The loader holds its skeleton for 250 ms after the tools arrive.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
    return setModalState;
  };

  const service = (key: string) =>
    document.body.querySelector<HTMLButtonElement>(
      `[data-testid="add-tool-service-${key}"]`,
    );

  it('lists services, presets included, before built-in tools', async () => {
    await render();
    const text = document.body.textContent ?? '';
    const services = text.indexOf('settings.tools.groupService');
    expect(services).toBeGreaterThan(-1);
    expect(services).toBeLessThan(text.indexOf('settings.tools.groupBuiltIn'));
    expect(service('mcp:notion')).not.toBeNull();
    // Sync-only and custom connectors are not tools here.
    expect(service('google_drive')).toBeNull();
    expect(service('custom_mcp')).toBeNull();
  });

  it('connects a service that is not connected yet', async () => {
    await render();
    await act(async () => service('mcp:notion')!.click());
    expect(launch).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'mcp:notion' }),
    );
  });

  it('opens a connected service to manage its tools', async () => {
    await render();
    await act(async () => service('telegram')!.click());
    expect(launch).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain('DRAWER');
  });
});
