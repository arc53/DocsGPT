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

// The drawer is tested on its own; here only what it is opened with.
const drawerProps = vi.hoisted(() => vi.fn());
vi.mock('../connectors/ConnectionDrawer', () => ({
  default: (props: {
    connector: { key: string } | null;
    onClose: () => void;
  }) => {
    drawerProps(props);
    return props.connector ? (
      <div data-testid="drawer">{props.connector.key}</div>
    ) : null;
  },
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
        state: 'custom',
      }),
      entry({
        key: 'custom_openapi',
        name: 'OpenAPI / REST',
        icon: 'api',
        publisher: 'custom',
        state: 'custom',
      }),
    ];
    drawerProps.mockClear();
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

  it('opens a connected service to manage its tools over the Tools page', async () => {
    const setModalState = await render();
    await act(async () => service('telegram')!.click());
    expect(launch).not.toHaveBeenCalled();
    expect(setModalState).toHaveBeenCalledWith('INACTIVE');
    expect(document.body.textContent).not.toContain('DRAWER');
    expect(
      document.body.querySelector('[data-testid="drawer"]')?.textContent,
    ).toBe('telegram');
  });

  it('draws a service as one tile: state first, the account in the footer', async () => {
    await render();
    const connected = service('telegram')!;
    const badges = Array.from(
      connected.querySelectorAll<HTMLElement>('[data-slot="badge"]'),
    );
    expect(badges[0].textContent).toBe('settings.connectors.status.connected');
    expect(connected.dataset.variant).toBe('outline');
    expect(connected.className).not.toMatch(/\bh-44\b/);
    const available = service('mcp:notion')!;
    // Available: no footer cue; no badge already says it isn't connected.
    expect(available.querySelector('[data-slot="card-footer"]')).toBeNull();
  });

  it('lists the custom kinds last and launches them in place', async () => {
    await render();
    const text = document.body.textContent ?? '';
    expect(text.indexOf('agents.form.toolsPopup.groupCustom')).toBeGreaterThan(
      text.indexOf('settings.tools.groupBuiltIn'),
    );
    const custom = (key: string) =>
      document.body.querySelector<HTMLButtonElement>(
        `[data-testid="add-tool-custom-${key}"]`,
      )!;
    expect(custom('custom_openapi')).not.toBeNull();
    // Nothing to be connected: no state, no cue.
    expect(
      custom('custom_mcp').querySelector('[data-slot="badge"]'),
    ).toBeNull();
    await act(async () => custom('custom_mcp').click());
    expect(launch).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'custom_mcp' }),
    );
  });

  it('ends on Cancel alone, with the Browse all link at the end of the body', async () => {
    await render();
    const dialog = document.body.querySelector('[role="dialog"]')!;
    const buttons = Array.from(dialog.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(buttons).not.toContain('settings.connectors.addCustom');
    expect(buttons).toContain('cancel');
    const link = Array.from(dialog.querySelectorAll('a')).find(
      (a) => a.textContent === 'settings.connectors.browseAll',
    )!;
    expect(link.getAttribute('href')).toBe('/settings/connectors');
    expect(link.querySelector('svg')!.getAttribute('class')).toContain(
      'size-3',
    );
    expect(dialog.textContent).not.toContain('settings.tools.browseConnectors');
  });

  it('keeps tool names as typed', async () => {
    await render();
    const titles = Array.from(
      document.body.querySelectorAll('[data-slot="card-title"]'),
    );
    expect(titles.length).toBeGreaterThan(0);
    for (const title of titles)
      expect(title.className).not.toContain('capitalize');
  });
});
