import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const api = vi.hoisted(() => ({
  createTool: vi.fn(),
  getUserTools: vi.fn(),
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
          {
            name: 'brave',
            displayName: 'Brave',
            description: 'Searches',
            configRequirements: {
              token: { type: 'string', label: 'Token', required: true },
            },
            actions: [],
            group: 'built_in',
          },
        ],
      }),
    })),
    createTool: (...a: unknown[]) => api.createTool(...a),
    getUserTools: (...a: unknown[]) => api.getUserTools(...a),
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
const launcher = vi.hoisted(() => ({
  options: null as null | {
    onConnected?: (toolIds: string[]) => void;
    onNavigate?: (to: string) => void;
  },
}));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: (options: NonNullable<typeof launcher.options>) => {
    launcher.options = options;
    return { launch, modals: null };
  },
}));
// The pairing dialog, as a stub that pairs on demand.
const pairing = vi.hoisted(() => ({
  onPaired: null as null | ((deviceId: string, name: string) => void),
}));
vi.mock('../settings/PairDeviceModal', () => ({
  default: (props: { onPaired?: (deviceId: string, name: string) => void }) => {
    pairing.onPaired = props.onPaired ?? null;
    return null;
  },
}));

// The drawer is tested on its own; here only what it is opened with.
const drawerProps = vi.hoisted(() => vi.fn());
vi.mock('../connectors/ConnectionDrawer', () => ({
  default: (props: {
    connector: { key: string } | null;
    onClose: () => void;
    onToolsCreated?: (ids: string[]) => void;
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

  const render = async (
    props: Partial<React.ComponentProps<typeof AddToolModal>> = {},
  ) => {
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
                    onToolsCreated={vi.fn()}
                    {...props}
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
    // Available: no state pill and no account; the meta line says only
    // what the service can do.
    expect(available.querySelector('[data-slot="badge"]')).toBeNull();
    expect(
      available.querySelector('[data-slot="card-footer"]')!.textContent,
    ).not.toContain('settings.connectors.status');
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
    // A trailing link icon: 12px from Button's link size, not its own class.
    expect(link.className).toContain("[&_svg:not([class*='size-'])]:size-3");
    expect(link.querySelector('svg')!.getAttribute('class')).not.toContain(
      'size-',
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

  describe('the tools it made, for a builder', () => {
    const ok = (body: unknown) => ({
      ok: true,
      status: 200,
      json: async () => body,
    });
    const tile = (title: string) =>
      Array.from(
        document.body.querySelectorAll<HTMLElement>('[data-slot="card"]'),
      ).find((card) => card.textContent?.includes(title))!;

    beforeEach(() => {
      api.createTool.mockReset().mockResolvedValue(ok({ id: 'tool-new' }));
      api.getUserTools.mockReset();
    });

    it('reports a built-in made with no setup', async () => {
      const onToolsCreated = vi.fn();
      const getUserTools = vi.fn();
      await render({ onToolsCreated, getUserTools });
      await act(async () => tile('Memory').click());
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-new']);
      // The builder reloads to put it on; no second reload.
      expect(getUserTools).not.toHaveBeenCalled();
    });

    it('reports a built-in made after its setup', async () => {
      const onToolsCreated = vi.fn();
      await render({ onToolsCreated });
      await act(async () => tile('Brave').click());
      const field = document.body.querySelector<HTMLInputElement>(
        '[role="dialog"] input:not([placeholder="Brave"])',
      )!;
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!;
      await act(async () => {
        setter.call(field, 'secret');
        field.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const add = Array.from(
        document.body.querySelectorAll<HTMLButtonElement>('button'),
      ).find((b) => b.textContent === 'modals.configTool.addButton')!;
      await act(async () => add.click());
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-new']);
    });

    it('reports the tools a connect set up', async () => {
      const onToolsCreated = vi.fn();
      await render({ onToolsCreated });
      launcher.options!.onConnected!(['tool-a', 'tool-b']);
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-a', 'tool-b']);
    });

    it("reports a paired device's tool", async () => {
      api.getUserTools.mockResolvedValue(
        ok({
          tools: [
            { id: 'other', name: 'remote_device', config: { device_id: 'x' } },
            {
              id: 'tool-dev',
              name: 'remote_device',
              config: { device_id: 'dev-1' },
            },
          ],
        }),
      );
      const onToolsCreated = vi.fn();
      await render({ onToolsCreated });
      await act(async () => pairing.onPaired!('dev-1', 'Laptop'));
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-dev']);
    });

    it('leaves through the builder from Browse all and a connect run', async () => {
      const onNavigate = vi.fn();
      await render({ onNavigate });
      expect(launcher.options!.onNavigate).toBe(onNavigate);
      const link = Array.from(document.body.querySelectorAll('a')).find(
        (a) => a.textContent === 'settings.connectors.browseAll',
      )!;
      await act(async () => link.click());
      expect(onNavigate).toHaveBeenCalledWith('/settings/connectors');
      expect(document.body.textContent).not.toContain('DRAWER');
    });

    it("reports the tools a connected service's drawer added, once it closes", async () => {
      const onToolsCreated = vi.fn();
      const getUserTools = vi.fn();
      await render({ onToolsCreated, getUserTools });
      await act(async () => service('telegram')!.click());
      const props = drawerProps.mock.calls.at(-1)![0] as {
        onClose: () => void;
        onToolsCreated: (ids: string[]) => void;
      };
      act(() => props.onToolsCreated(['tool-a']));
      expect(onToolsCreated).not.toHaveBeenCalled();
      await act(async () => props.onClose());
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-a']);
      expect(getUserTools).not.toHaveBeenCalled();
      // Closed with nothing added: a plain reload.
      await act(async () => service('telegram')!.click());
      const again = drawerProps.mock.calls.at(-1)![0] as {
        onClose: () => void;
      };
      await act(async () => again.onClose());
      expect(getUserTools).toHaveBeenCalledTimes(1);
    });

    // A reconnect or Sync more leaves the drawer without closing it: what
    // its Add tools made goes on then, not with a later drawer's close.
    it("reports the drawer's tools before a connect run it starts", async () => {
      const onToolsCreated = vi.fn();
      await render({ onToolsCreated });
      await act(async () => service('telegram')!.click());
      const props = drawerProps.mock.calls.at(-1)![0] as {
        onToolsCreated: (ids: string[]) => void;
        onConnect: (connector: { key: string }, options?: object) => void;
      };
      act(() => props.onToolsCreated(['tool-a']));
      await act(async () => props.onConnect({ key: 'telegram' }));
      expect(onToolsCreated).toHaveBeenCalledWith(['tool-a']);
      expect(launch).toHaveBeenCalled();

      await act(async () => service('telegram')!.click());
      const again = drawerProps.mock.calls.at(-1)![0] as {
        onClose: () => void;
      };
      await act(async () => again.onClose());
      expect(onToolsCreated).toHaveBeenCalledTimes(1);
    });
  });
});
