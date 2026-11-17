import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A name the string carries shows as `key(name)`.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string' ? `${key}(${opts.name})` : key,
  }),
}));

const service = vi.hoisted(() => ({
  createConnection: vi.fn(),
  setup: vi.fn(),
  reconnect: vi.fn(),
  getConnection: vi.fn(),
  getCatalog: vi.fn(),
  listConnections: vi.fn(),
  renameConnection: vi.fn(),
  setToolPermissions: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

const userApi = vi.hoisted(() => ({
  testMCPConnection: vi.fn(),
  saveMCPServer: vi.fn(),
  getConfig: vi.fn(),
  getSourceDefaults: vi.fn(),
}));
vi.mock('../api/services/userService', async (importOriginal) => {
  const original = await importOriginal<{ default: object }>();
  return { default: { ...original.default, ...userApi } };
});

// The popup is ConnectorAuth's own business: here it records what it was
// started with and reports a finished sign-in.
const auth = vi.hoisted(() => ({ options: vi.fn() }));
vi.mock('../components/ConnectorAuth', () => ({
  useConnectorAuth: (options: {
    onSuccess: (data: { connection_id: string; user_email: string }) => void;
  }) => {
    auth.options(options);
    return () =>
      options.onSuccess({
        connection_id: 'conn-t1',
        user_email: 'drive@operations.io',
      });
  },
}));
vi.mock('../components/GoogleDrivePicker', () => ({
  default: () => <div data-testid="google-picker" />,
}));
vi.mock('../components/FilePicker', () => ({
  FilePicker: () => <div data-testid="file-picker" />,
}));

import notificationsReducer from '../notifications/notificationsSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import workspaceReducer, { PERSONAL_ROW } from '../workspace/workspaceSlice';
import connectorsReducer from './connectorsSlice';
import ConnectWizard from './ConnectWizard';
import type { Connection, ConnectorDefinition } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const tokenFor = (user: string) =>
  `h.${btoa(JSON.stringify({ sub: user })).replace(/=+$/, '')}.s`;

const base: ConnectorDefinition = {
  key: 'telegram',
  name: 'Telegram',
  description: 'Send messages.',
  icon: 'tool_telegram',
  category: 'messaging',
  auth_kind: 'api_key',
  capabilities: ['write'],
  credential_fields: [
    { key: 'token', label: 'Bot token', secret: true, required: true },
  ],
  setup_fields: [],
  sync_ingestor: null,
  default_sync_frequency: 'weekly',
  tool_templates: [],
  setup: { tools: 'off', sync: 'off' },
  mcp_url: null,
  publisher: 'built_in',
  docs_url: null,
  oauth_scopes: [],
  available: true,
  disabled: false,
  needs_setup: false,
  missing_settings: [],
  connected_count: 0,
  connection_count: 0,
  status: null,
  state: 'available',
  credential_policy: 'choose',
};

const drive: ConnectorDefinition = {
  ...base,
  key: 'google_drive',
  name: 'Google Drive',
  icon: 'drive',
  category: 'files',
  auth_kind: 'oauth',
  capabilities: ['sync'],
  credential_fields: [],
  sync_ingestor: 'google_drive',
  setup: { tools: 'off', sync: 'ask' },
};

/** The team's Drive account, connected by Lena. */
const teamDrive = (overrides: Partial<Connection> = {}): Connection => ({
  id: 'conn-t1',
  connector_key: 'google_drive',
  name: 'Google Drive',
  display_name: null,
  icon: 'drive',
  account_label: 'drive@operations.io',
  auth_kind: 'oauth',
  status: 'connected',
  server_url: null,
  last_error: null,
  created_at: null,
  updated_at: null,
  last_used_at: null,
  source_count: 1,
  tool_count: 0,
  owner: 'team',
  team_id: 't1',
  connected_by: { user_id: 'lena', label: 'lena@operations.io' },
  paused_for: null,
  allowed_actions: ['view', 'sync', 'manage'],
  can_pick: false,
  ...overrides,
});

describe('ConnectWizard for a team', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    auth.options.mockReset();
    service.getCatalog.mockResolvedValue({ success: true, connectors: [] });
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [],
    });
    userApi.getConfig.mockResolvedValue({ json: async () => ({}) });
    userApi.getSourceDefaults.mockResolvedValue({ ok: false });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    setRequestWorkspace('t1', 0);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
    setRequestWorkspace('personal', 0);
  });

  /**
   * Renders the wizard in team `t1` for `me`, the team holding
   * `connections`; a reload answers with `reloaded` for the team.
   */
  const render = async (
    connector: ConnectorDefinition,
    props: Partial<Parameters<typeof ConnectWizard>[0]> = {},
    {
      me = 'ana',
      connections = [],
      reloaded = connections,
    }: {
      me?: string;
      connections?: Connection[];
      reloaded?: Connection[];
    } = {},
  ) => {
    service.listConnections.mockImplementation(
      async (_token: unknown, options?: { owner?: string }) => ({
        success: true,
        connections: options?.owner === 'team' ? reloaded : [],
      }),
    );
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        notifications: notificationsReducer,
        preference: (state = { token: tokenFor(me) }) => state,
        workspace: workspaceReducer,
        conversation: (state = {}) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          catalog: [],
          connections: [],
          loading: false,
          loaded: true,
          failed: false,
          teams: {
            t1: {
              catalog: [],
              connections,
              loading: false,
              loaded: true,
              failed: false,
              latestRequestId: null,
            },
          },
        },
        workspace: {
          current: 't1',
          workspaces: [
            PERSONAL_ROW,
            {
              id: 't1',
              kind: 'team' as const,
              name: 'Operations',
              role: 'admin' as const,
            },
          ],
          loaded: true,
          loading: false,
          epoch: 0,
          lastReason: null,
          latestRequestId: null,
        },
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <ConnectWizard
              connector={connector}
              onClose={vi.fn()}
              owner="team"
              {...props}
            />
          </MemoryRouter>
        </Provider>,
      );
    });
    return store;
  };

  const text = () => document.body.textContent ?? '';
  const title = () =>
    document.body.querySelector('[data-slot="modal-header"] h2')?.textContent;
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === label);
  const click = async (label: string) => {
    const target = button(label);
    expect(target, `button ${label}`).toBeDefined();
    await act(async () => target!.click());
  };
  const typeInto = async (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  it('a pasted key connects for the team', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-t9', account_label: '…1c26' },
    });
    await render(base);
    await typeInto(
      document.body.querySelector<HTMLInputElement>('input[type="password"]')!,
      '123:abc',
    );
    await click('settings.connectors.status.connect');
    expect(service.createConnection).toHaveBeenCalledWith(
      expect.objectContaining({ connector_key: 'telegram', owner: 'team' }),
      expect.anything(),
    );
  });

  it("a team's refusal reads in the app's words", async () => {
    service.createConnection.mockResolvedValue({
      success: false,
      error: 'account_already_connected',
      connection_id: 'conn-t1',
    });
    await render(base);
    await typeInto(
      document.body.querySelector<HTMLInputElement>('input[type="password"]')!,
      '123:abc',
    );
    await click('settings.connectors.status.connect');
    expect(text()).toContain(
      'settings.connectors.team.errors.accountAlreadyConnected',
    );
  });

  it("another Admin's key reconnect fills every field, and a key the team already has reads in the app's words", async () => {
    const teamBot = teamDrive({
      connector_key: 'telegram',
      name: 'Telegram',
      auth_kind: 'api_key',
      account_label: '…1c26',
    });
    service.getConnection.mockResolvedValue({
      success: true,
      connection: { ...teamBot, sources: [], tools: [] },
    });
    service.reconnect.mockResolvedValue({
      success: false,
      error: 'account_already_connected',
      connection_id: 'conn-t2',
    });
    await render(
      base,
      { mode: 'reconnect', connectionId: 'conn-t1' },
      { connections: [teamBot] },
    );
    // Nothing of the old key is kept: the required field starts empty.
    expect(button('settings.connectors.team.reconnect.confirm')?.disabled).toBe(
      true,
    );
    await typeInto(
      document.body.querySelector<HTMLInputElement>('input[type="password"]')!,
      '123:abc',
    );
    await click('settings.connectors.team.reconnect.confirm');
    expect(service.reconnect).toHaveBeenCalledWith(
      'conn-t1',
      { credentials: { token: '123:abc' } },
      expect.anything(),
    );
    expect(text()).toContain(
      'settings.connectors.team.errors.accountAlreadyConnected',
    );
  });

  it('a sign-in connects for the team', async () => {
    await render(drive);
    expect(auth.options).toHaveBeenLastCalledWith(
      expect.objectContaining({ provider: 'google_drive', owner: 'team' }),
    );
  });

  it('whoever connects it goes on to choose what to sync', async () => {
    await render(
      drive,
      {},
      {
        reloaded: [
          teamDrive({
            connected_by: { user_id: 'ana', label: 'ana@operations.io' },
            allowed_actions: ['view', 'sync', 'manage', 'pick'],
            can_pick: true,
          }),
        ],
      },
    );
    await click('settings.connectors.wizard.signIn(Google Drive)');
    expect(title()).toBe(
      'settings.connectors.wizard.chooseWhatToSyncFrom(Google Drive)',
    );
  });

  it('with no right to browse the account, the sync step never shows', async () => {
    await render(drive, {}, { reloaded: [teamDrive({ can_pick: false })] });
    await click('settings.connectors.wizard.signIn(Google Drive)');
    expect(title()).toBe('settings.connectors.wizard.doneTitle(Google Drive)');
    expect(button('settings.connectors.syncContent')).toBeUndefined();
    expect(document.querySelector('[data-testid="google-picker"]')).toBe(null);
  });

  it("another Admin reconnecting is told the account becomes theirs, with the connection's sources", async () => {
    service.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...teamDrive(),
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
        tools: [],
      },
    });
    await render(
      drive,
      { mode: 'reconnect', connectionId: 'conn-t1' },
      { connections: [teamDrive()] },
    );
    expect(title()).toBe('settings.connectors.team.reconnect.title');
    expect(text()).toContain(
      'settings.connectors.team.reconnect.body(lena@operations.io)',
    );
    expect(text()).toContain('Handbook');
    expect(text()).toContain('settings.connectors.team.reconnect.dropNote');
    // The sign-in names the connection; the server replaces its account.
    expect(auth.options).toHaveBeenLastCalledWith(
      expect.objectContaining({ connectionId: 'conn-t1' }),
    );
    await click('settings.connectors.team.reconnect.confirm');
    expect(title()).toBe('settings.connectors.wizard.doneTitle(Google Drive)');
  });

  it('whoever connected it reconnects as before', async () => {
    await render(
      drive,
      { mode: 'reconnect', connectionId: 'conn-t1' },
      { me: 'lena', connections: [teamDrive()] },
    );
    expect(title()).toBe(
      'settings.connectors.wizard.reconnectTitle(Google Drive)',
    );
    expect(text()).not.toContain('settings.connectors.team.reconnect.body');
    expect(service.getConnection).not.toHaveBeenCalled();
  });

  describe("a team's MCP sign-in saved from the server form", () => {
    const customMcp: ConnectorDefinition = {
      ...base,
      key: 'custom_mcp',
      name: 'MCP server',
      icon: 'tool_mcp_tool',
      auth_kind: 'mcp',
      credential_fields: [],
      tool_templates: ['mcp_tool'],
      publisher: 'custom',
    };
    /** The team's sign-in to a custom server, made by `ana` just now. */
    const teamMcp = teamDrive({
      id: 'conn-mcp',
      connector_key: 'custom_mcp',
      name: 'Carrier Rates',
      icon: 'tool_mcp_tool',
      account_label: 'ops@carrier.example',
      auth_kind: 'mcp_oauth',
      server_url: 'https://rates.example.com',
      source_count: 0,
      tool_count: 1,
      connected_by: { user_id: 'ana', label: 'ana@operations.io' },
      allowed_actions: ['view', 'sync', 'manage', 'pick'],
      can_pick: true,
    });
    const savedTool = {
      id: 'tool-m',
      name: 'mcp_tool',
      display_name: 'Carrier Rates',
      status: true,
      credential_mode: 'owner',
      actions: [
        {
          name: 'quote',
          description: 'Quote a lane.',
          access: 'write',
          permission: 'ask',
        },
      ],
    };

    beforeEach(() => {
      service.getConnection.mockResolvedValue({
        success: true,
        connection: { ...teamMcp, tools: [savedTool], sources: [] },
      });
      service.setToolPermissions.mockResolvedValue({
        success: true,
        tool: savedTool,
      });
    });

    it("ends on the summary of the team's account, with its tool", async () => {
      const onClose = vi.fn();
      await render(
        customMcp,
        { mode: 'done', connectionId: 'conn-mcp', onClose },
        { connections: [teamMcp] },
      );
      expect(title()).toBe(
        'settings.connectors.wizard.doneTitle(settings.connectors.custom.custom_mcp)',
      );
      expect(service.getConnection).toHaveBeenCalledWith(
        'conn-mcp',
        expect.anything(),
      );
      // The account the team signed in with, and the tool it set up.
      expect(text()).toContain('settings.connectors.wizard.doneSummaryNone');
      expect(text()).toContain('settings.connectors.wizard.toolsHeading');
      // Nothing to sync from a server, so it never offers to.
      expect(button('settings.connectors.syncContent')).toBeUndefined();
      await click('settings.connectors.wizard.tryInChat');
      expect(onClose).toHaveBeenCalledWith(true, []);
    });

    it("sets the tool's permissions on the team's account", async () => {
      await render(
        customMcp,
        { mode: 'done', connectionId: 'conn-mcp' },
        { connections: [teamMcp] },
      );
      const always = document.body.querySelector<HTMLButtonElement>(
        '[data-permission="always"]',
      );
      expect(always).not.toBeNull();
      await act(async () => always!.click());
      expect(service.setToolPermissions).toHaveBeenCalledWith(
        'conn-mcp',
        'tool-m',
        { quote: 'always' },
        expect.anything(),
      );
    });

    it('names the account before the team list is read again', async () => {
      await render(
        customMcp,
        { mode: 'done', connectionId: 'conn-mcp' },
        { connections: [] },
      );
      expect(text()).toContain('settings.connectors.wizard.doneSummaryNone');
    });
  });
});
