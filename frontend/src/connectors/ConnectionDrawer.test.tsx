import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const connectors = vi.hoisted(() => ({
  getConnection: vi.fn(),
  getCatalog: vi.fn(async () => ({ success: true, connectors: [] })),
  listConnections: vi.fn(async () => ({ success: true, connections: [] })),
  setup: vi.fn(),
  renameConnection: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: connectors }));

const users = vi.hoisted(() => ({
  updateToolStatus: vi.fn(),
  syncConnector: vi.fn(),
  syncSource: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: users }));

import actionToastReducer, {
  selectActionToast,
} from '../notifications/actionToastSlice';
import ConnectionDrawer from './ConnectionDrawer';
import connectorsReducer from './connectorsSlice';
import type { ConnectorDefinition } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const DRIVE = {
  key: 'google_drive',
  name: 'Google Drive',
  description: 'Sync files.',
  icon: 'drive',
  publisher: 'built_in',
  auth_kind: 'oauth',
  capabilities: ['sync'],
  setup: { tools: 'off', sync: 'ask' },
  sync_ingestor: 'google_drive',
  available: true,
  needs_setup: false,
  missing_settings: [],
} as unknown as ConnectorDefinition;

const DETAIL = {
  id: 'conn-1',
  connector_key: 'google_drive',
  auth_kind: 'oauth',
  account_label: 'lena@example.com',
  status: 'connected',
  last_error: null,
  server_url: null,
  sources: [
    {
      id: 'src-1',
      name: 'Handbook',
      type: 'connector:file',
      last_sync: null,
      sync_frequency: 'weekly',
      sync_state: 'active',
    },
  ],
  tools: [
    {
      id: 'tool-1',
      name: 'mcp_tool',
      display_name: 'Drive search',
      status: true,
      credential_mode: 'owner',
      actions: [],
    },
  ],
};

describe('ConnectionDrawer', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;
  const makeStore = () =>
    configureStore({
      reducer: {
        connectors: connectorsReducer,
        actionToast: actionToastReducer,
        preference: (state = { token: null }) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          loading: false,
          loaded: true,
          failed: false,
          catalog: [DRIVE],
          connections: [
            {
              id: 'conn-1',
              connector_key: 'google_drive',
              status: 'connected',
            },
            { id: 'conn-gh', connector_key: 'github', status: 'connected' },
          ],
        },
        preference: { token: null },
      },
    } as Parameters<typeof configureStore>[0]);

  beforeEach(() => {
    Object.values(users).forEach((fn) => fn.mockReset());
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: DETAIL,
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (connector: ConnectorDefinition = DRIVE) => {
    store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <ConnectionDrawer
            connector={connector}
            onClose={vi.fn()}
            onConnect={vi.fn()}
          />
        </Provider>,
      );
    });
  };

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === text)!;

  it('turns a tool on and off from its connection page', async () => {
    users.updateToolStatus.mockResolvedValue({ ok: true });
    await render();
    const toggle = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.connectors.detail.toolSwitch"]',
    )!;
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    await act(async () => toggle.click());
    expect(users.updateToolStatus).toHaveBeenCalledWith(
      { id: 'tool-1', status: false },
      null,
    );
    expect(toggle.getAttribute('aria-checked')).toBe('false');
  });

  it('puts the switch back when the change fails', async () => {
    users.updateToolStatus.mockResolvedValue({ ok: false });
    await render();
    const toggle = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.connectors.detail.toolSwitch"]',
    )!;
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(
      selectActionToast(
        store.getState() as Parameters<typeof selectActionToast>[0],
      )?.variant,
    ).toBe('destructive');
  });

  it('syncs a source now through its connection', async () => {
    users.syncConnector.mockResolvedValue({
      json: async () => ({ success: true }),
    });
    await render();
    await act(async () => button('settings.connectors.detail.syncNow').click());
    expect(users.syncConnector).toHaveBeenCalledWith('src-1', null);
    expect(users.syncSource).not.toHaveBeenCalled();
    expect(
      selectActionToast(
        store.getState() as Parameters<typeof selectActionToast>[0],
      )?.variant,
    ).toBe('success');
  });

  it('says in plain words that an expired sign-in needs redoing', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        status: 'reconnect_needed',
        last_error: 'invalid_grant: token expired',
      },
    });
    await render();
    const text = document.body.textContent ?? '';
    expect(text).toContain('settings.connectors.detail.expired');
    expect(text).toContain('settings.connectors.detail.account');
    expect(text).not.toContain('settings.connectors.detail.connectedAs');
    // The provider's message stays available on hover, not as the sentence.
    expect(text).not.toContain('invalid_grant');
    expect(
      document.body.querySelector('[title="invalid_grant: token expired"]'),
    ).not.toBeNull();
  });

  const openAccountMenu = async () => {
    const trigger = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.connectors.detail.accountMenu"]',
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  };

  it('shows the name an account was given, with the account under it', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: { ...DETAIL, account_name: 'Work' },
    });
    await render();
    const text = document.body.textContent ?? '';
    expect(text).toContain('Work');
    expect(text).toContain('settings.connectors.detail.connectedAs');
  });

  it('renames an account from its menu', async () => {
    connectors.renameConnection.mockResolvedValue({
      success: true,
      connection: { ...DETAIL, account_name: 'Work' },
    });
    await render();
    await openAccountMenu();
    const item = Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === 'settings.connectors.detail.rename')!;
    await act(async () => item.click());
    const input =
      document.body.querySelector<HTMLInputElement>('#rename-account')!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, 'Work');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => button('settings.connectors.rename.save').click());
    expect(connectors.renameConnection).toHaveBeenCalledWith(
      'conn-1',
      'Work',
      null,
    );
  });

  it('labels synced content as Knowledge from this connection', async () => {
    await render();
    expect(document.body.textContent).toContain(
      'settings.connectors.detail.sources',
    );
    expect(document.body.textContent).not.toContain(
      'settings.connectors.publisher',
    );
  });

  describe('GitHub', () => {
    const GITHUB = {
      ...DRIVE,
      key: 'github',
      name: 'GitHub',
      icon: 'github',
      auth_kind: 'api_key',
      capabilities: ['sync', 'read'],
      setup: { tools: 'ask', sync: 'ask' },
      sync_ingestor: 'github',
      tool_templates: ['mcp_tool'],
    } as unknown as ConnectorDefinition;
    const TOKEN_DETAIL = {
      ...DETAIL,
      connector_key: 'github',
      auth_kind: 'api_key',
      account_label: 'octocat',
      sources: [],
      tools: [],
    };

    beforeEach(() => {
      connectors.setup.mockReset();
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: TOKEN_DETAIL,
      });
    });

    it('names a token connection by its account, not as a key hint', async () => {
      await render(GITHUB);
      expect(document.body.textContent).toContain(
        'settings.connectors.detail.connectedAs',
      );
      expect(document.body.textContent).not.toContain(
        'settings.connectors.detail.keyEnding',
      );
    });

    it('adds the tools a connection skipped during setup', async () => {
      connectors.setup.mockResolvedValue({ success: true, tools: [] });
      await render(GITHUB);
      await act(async () =>
        button('settings.connectors.detail.addTools').click(),
      );
      expect(connectors.setup).toHaveBeenCalledWith(
        'conn-1',
        { create_tools: true },
        null,
      );
    });
  });
});
