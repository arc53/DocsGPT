import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A name the string carries shows as `key(name)`, so who is named can be
    // checked; a pause reason shows as `key[reason]`.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string'
        ? `${key}(${opts.name})`
        : opts && typeof opts.reason === 'string'
          ? `${key}[${opts.reason}]`
          : key,
  }),
}));

const connectors = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  listConnections: vi.fn(),
  getConnection: vi.fn(),
  disconnect: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: connectors }));
const users = vi.hoisted(() => ({
  updateToolStatus: vi.fn(),
  syncConnector: vi.fn(),
  syncSource: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: users }));
// The wizard is tested on its own; here only what it is opened with matters.
const launch = vi.hoisted(() => vi.fn());
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
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
import type {
  Connection,
  ConnectionAction,
  ConnectorDefinition,
} from '../connectors/types';
import actionToastReducer from '../notifications/actionToastSlice';
import notificationsReducer from '../notifications/notificationsSlice';
import { setRequestWorkspace } from '../workspace/requestWorkspace';
import workspaceReducer, {
  PERSONAL_ROW,
  type WorkspaceRole,
} from '../workspace/workspaceSlice';
import Connectors from './Connectors';
import CustomModels from './CustomModels';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** A token whose `sub` is `user`, as the app reads the reader's id. */
const tokenFor = (user: string) =>
  `h.${btoa(JSON.stringify({ sub: user })).replace(/=+$/, '')}.s`;

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

const makeStore = (role?: WorkspaceRole, me = 'ana') =>
  configureStore({
    reducer: {
      connectors: connectorsReducer,
      actionToast: actionToastReducer,
      notifications: notificationsReducer,
      preference: (state = { token: tokenFor(me) }) => state,
      workspace: workspaceReducer,
    },
    preloadedState: { workspace: workspaceState(role) },
  });

const definition = (
  overrides: Partial<ConnectorDefinition>,
): ConnectorDefinition => ({
  key: 'google_drive',
  name: 'Google Drive',
  description: 'Sync files.',
  icon: 'drive',
  category: 'files',
  auth_kind: 'oauth',
  capabilities: ['sync'],
  credential_fields: [],
  setup_fields: [],
  sync_ingestor: 'google_drive',
  default_sync_frequency: 'weekly',
  tool_templates: [],
  setup: { tools: 'off', sync: 'ask' },
  mcp_url: null,
  publisher: 'built_in',
  docs_url: null,
  oauth_scopes: [],
  available: true,
  disabled: false,
  needs_setup: false,
  missing_settings: [],
  connected_count: 1,
  connection_count: 1,
  status: 'connected',
  state: 'connected',
  credential_policy: 'choose',
  ...overrides,
});

const DRIVE = definition({});
const S3 = definition({
  key: 's3',
  name: 'Amazon S3',
  auth_kind: 'api_key',
  connected_count: 0,
  connection_count: 0,
  status: null,
  state: 'available',
});
const CUSTOM = definition({
  key: 'custom_mcp',
  name: 'Custom MCP',
  auth_kind: 'mcp',
  publisher: 'custom',
  connected_count: 0,
  connection_count: 0,
  status: null,
  state: 'custom',
});

const ACTIONS: Record<WorkspaceRole, ConnectionAction[]> = {
  viewer: ['view'],
  editor: ['view', 'sync'],
  admin: ['view', 'sync', 'manage'],
  owner: ['view', 'sync', 'manage'],
};

/** The team's Drive account, as the caller with `role` reads it. */
const teamDrive = (
  role: WorkspaceRole,
  overrides: Partial<Connection> = {},
): Connection => ({
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
  allowed_actions: ACTIONS[role],
  can_pick: false,
  ...overrides,
});

const detailOf = (connection: Connection) => ({
  ...connection,
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
});

describe('Connectors page in a team', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;

  beforeEach(() => {
    Object.values(connectors).forEach((fn) => fn.mockReset());
    Object.values(customModels).forEach((fn) => fn.mockReset());
    launch.mockReset();
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
    setRequestWorkspace('personal', 0);
  });

  /** The team's lists answer with `connections` and the catalog. */
  const teamAnswers = (
    connections: Connection[],
    catalog: ConnectorDefinition[] = [DRIVE, S3, CUSTOM],
  ) => {
    connectors.getCatalog.mockImplementation(
      async (_token: unknown, options?: { owner?: string }) => ({
        success: true,
        connectors: options?.owner === 'team' ? catalog : [],
      }),
    );
    connectors.listConnections.mockImplementation(
      async (_token: unknown, options?: { owner?: string }) => ({
        success: true,
        connections: options?.owner === 'team' ? connections : [],
      }),
    );
    connectors.getConnection.mockImplementation(async (id: string) => {
      const row = connections.find((c) => c.id === id);
      return row
        ? { success: true, connection: detailOf(row) }
        : { success: false };
    });
  };

  const render = async (
    page: 'connectors' | 'models',
    role?: WorkspaceRole,
    me = 'ana',
  ) => {
    store = makeStore(role, me);
    setRequestWorkspace(role ? 't1' : 'personal', 0);
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

  const text = () => document.body.textContent ?? '';
  const card = (key: string) =>
    container.querySelector<HTMLButtonElement>(
      `[data-testid="connector-card-${key}"]`,
    );
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === label);
  const openDrawer = async () => {
    await act(async () => card('google_drive')!.click());
  };
  const accountMenu = () =>
    document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.connectors.detail.accountMenu"]',
    );
  const openMenu = async (label: string) => {
    const trigger = document.body.querySelector<HTMLButtonElement>(
      `[aria-label="${label}"]`,
    )!;
    await act(async () => {
      trigger.dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
      trigger.click();
    });
  };
  const menuLabels = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).map((el) => el.textContent);

  it("reads the team's list with owner=team and says the accounts are the team's, with no Personal-only notice", async () => {
    teamAnswers([teamDrive('viewer')]);
    await render('connectors', 'viewer');
    expect(connectors.listConnections).toHaveBeenCalledWith(expect.anything(), {
      owner: 'team',
      workspace: 't1',
    });
    expect(connectors.getCatalog).toHaveBeenCalledWith(expect.anything(), {
      owner: 'team',
      workspace: 't1',
    });
    expect(
      container.querySelector('[data-testid="personal-only-notice"]'),
    ).toBe(null);
    expect(container.querySelector('[data-slot="alert"]')).toBe(null);
    expect(text()).toContain('settings.connectors.team.notice');
    expect(card('google_drive')).not.toBe(null);
  });

  it('a Viewer sees only what the team connected: no catalog to connect, no custom connector', async () => {
    teamAnswers([teamDrive('viewer')]);
    await render('connectors', 'viewer');
    expect(card('google_drive')).not.toBe(null);
    expect(card('s3')).toBe(null);
    expect(button('settings.connectors.addCustom')).toBeUndefined();
  });

  it('an Editor gets no catalog to connect either', async () => {
    teamAnswers([teamDrive('editor')]);
    await render('connectors', 'editor');
    expect(card('s3')).toBe(null);
    expect(button('settings.connectors.addCustom')).toBeUndefined();
  });

  it('an Admin adds a custom server for the team', async () => {
    teamAnswers([teamDrive('admin')]);
    await render('connectors', 'admin');
    expect(button('settings.connectors.addCustom')).toBeDefined();
  });

  it('with nothing connected, a Viewer reads that an Admin can connect one', async () => {
    teamAnswers([], [S3]);
    await render('connectors', 'viewer');
    expect(card('s3')).toBe(null);
    expect(text()).toContain('settings.connectors.team.emptyMember');
  });

  it("a card names who connected the team's account", async () => {
    teamAnswers([teamDrive('viewer')]);
    await render('connectors', 'viewer');
    expect(card('google_drive')!.textContent).toContain(
      'settings.connectors.team.connectedBy(lena@operations.io)',
    );
  });

  it('a Viewer opens the account read-only: who connected it, why it is read-only, no account menu, no Sync now, no Sync more', async () => {
    teamAnswers([teamDrive('viewer')]);
    await render('connectors', 'viewer');
    await openDrawer();
    expect(text()).toContain(
      'settings.connectors.team.connectedBy(lena@operations.io)',
    );
    expect(text()).toContain('settings.connectors.team.adminOnly');
    expect(accountMenu()).toBe(null);
    expect(button('settings.connectors.detail.syncMore')).toBeUndefined();
    expect(button('settings.connectors.detail.connectAnother')).toBeUndefined();
    await openMenu('settings.connectors.detail.sourceMenu');
    expect(menuLabels()).not.toContain('settings.connectors.detail.syncNow');
    expect(menuLabels()).toContain('settings.connectors.openInKnowledge');
  });

  it('an Editor may Sync now but not manage the account', async () => {
    teamAnswers([teamDrive('editor')]);
    await render('connectors', 'editor');
    await openDrawer();
    expect(accountMenu()).toBe(null);
    await openMenu('settings.connectors.detail.sourceMenu');
    expect(menuLabels()).toContain('settings.connectors.detail.syncNow');
  });

  it('an Admin connects a catalog service for the team', async () => {
    teamAnswers([teamDrive('admin')]);
    await render('connectors', 'admin');
    expect(card('s3')).not.toBe(null);
    await act(async () => card('s3')!.click());
    expect(launch).toHaveBeenCalledWith(
      expect.objectContaining({ key: 's3' }),
      expect.objectContaining({ owner: 'team' }),
    );
  });

  it("an Admin manages a teammate's account but can't browse it: account menu, no Sync more, a line naming who can", async () => {
    teamAnswers([teamDrive('admin')]);
    await render('connectors', 'admin');
    await openDrawer();
    expect(text()).not.toContain('settings.connectors.team.adminOnly');
    await openMenu('settings.connectors.detail.accountMenu');
    expect(menuLabels()).toEqual(
      expect.arrayContaining([
        'settings.connectors.detail.rename',
        'settings.connectors.detail.disconnect',
        'settings.connectors.detail.remove',
      ]),
    );
    expect(button('settings.connectors.detail.syncMore')).toBeUndefined();
    expect(text()).toContain(
      'settings.connectors.team.pickerOwnerOnly(lena@operations.io)',
    );
  });

  it('whoever connected it syncs more from it, for the team', async () => {
    teamAnswers([
      teamDrive('admin', {
        allowed_actions: ['view', 'sync', 'manage', 'pick'],
        can_pick: true,
      }),
    ]);
    await render('connectors', 'admin', 'lena');
    await openDrawer();
    expect(text()).toContain('settings.connectors.team.connectedByYou');
    await act(async () =>
      button('settings.connectors.detail.syncMore')!.click(),
    );
    expect(launch).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'google_drive' }),
      expect.objectContaining({
        mode: 'sync',
        connectionId: 'conn-t1',
        owner: 'team',
      }),
    );
  });

  it('a paused account says why; an Admin reconnects it for the team or disconnects it', async () => {
    const paused = teamDrive('admin', {
      status: 'paused',
      paused_for: { reason: 'payer_left', until: null, left_team: true },
    });
    teamAnswers([paused], [definition({ state: 'paused' })]);
    await render('connectors', 'admin');
    expect(card('google_drive')!.textContent).toContain(
      'settings.connectors.status.paused',
    );
    await openDrawer();
    expect(text()).toContain('settings.connectors.team.paused[');
    expect(text()).toContain('settings.connectors.team.pausedHintAdmin');
    await openMenu('settings.connectors.detail.accountMenu');
    expect(menuLabels()).toContain('settings.connectors.detail.disconnect');
    const reconnect = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).filter(
      (b) => b.textContent?.trim() === 'settings.connectors.status.reconnect',
    );
    expect(reconnect.length).toBeGreaterThan(0);
    await act(async () => reconnect[0].click());
    expect(launch).toHaveBeenCalledWith(
      expect.objectContaining({ key: 'google_drive' }),
      expect.objectContaining({
        mode: 'reconnect',
        connectionId: 'conn-t1',
        owner: 'team',
      }),
    );
  });

  it('a Viewer sees why it is paused, with no way to reconnect', async () => {
    const paused = teamDrive('viewer', {
      status: 'paused',
      paused_for: { reason: 'payer_left', until: null, left_team: true },
    });
    teamAnswers([paused], [definition({ state: 'paused' })]);
    await render('connectors', 'viewer');
    await openDrawer();
    expect(text()).toContain('settings.connectors.team.paused[');
    expect(text()).toContain('settings.connectors.team.pausedHintMember');
    expect(button('settings.connectors.status.reconnect')).toBeUndefined();
  });

  it('Connectors in Personal: the catalog as before, the caller’s own', async () => {
    await render('connectors');
    expect(connectors.getCatalog).toHaveBeenCalled();
    expect(connectors.listConnections).not.toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ owner: 'team' }),
    );
    expect(text()).not.toContain('settings.connectors.team.notice');
  });

  const switchButton = () =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === 'settings.connectors.personalOnly.switch',
    );

  it('Custom models in a team: says models are personal and loads nothing', async () => {
    await render('models', 'editor');
    expect(
      container.querySelector<HTMLElement>('[data-slot="alert"]')?.textContent,
    ).toContain('settings.customModels.personalOnly');
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
