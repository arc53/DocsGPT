import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    // A name the string carries shows as `key(name)`, so titles can be checked.
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && typeof opts.name === 'string' ? `${key}(${opts.name})` : key,
  }),
}));

const connectors = vi.hoisted(() => ({
  getConnection: vi.fn(),
  getCatalog: vi.fn(async () => ({ success: true, connectors: [] })),
  listConnections: vi.fn(async () => ({
    success: true,
    connections: [] as Record<string, unknown>[],
  })),
  setup: vi.fn(),
  renameConnection: vi.fn(),
  setWrites: vi.fn(),
  disconnect: vi.fn(),
  remove: vi.fn(),
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
import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import ConnectionDrawer from './ConnectionDrawer';
import connectorsReducer, {
  selectStartedSyncs,
  syncStarted,
  type StartedSync,
} from './connectorsSlice';
import type { ConnectorDefinition } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** Where a source row leads, with the source it opens. */
function KnowledgePage() {
  return <div>KNOWLEDGE{useLocation().search}</div>;
}

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
  name: 'Google Drive',
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

const PART = {
  ...DRIVE,
  key: 'mcp:atlassian',
  name: 'Jira & Confluence',
  description: 'Search Jira.',
  capabilities: ['read', 'write'],
  setup: { tools: 'auto', sync: 'off' },
  sync_ingestor: null,
  part_of: 'google_drive',
} as unknown as ConnectorDefinition;

describe('ConnectionDrawer', () => {
  let container: HTMLDivElement;
  let root: Root;
  let store: ReturnType<typeof makeStore>;
  const makeStore = (
    extra: Record<string, unknown>[] = [],
    {
      loaded = true,
      own = true,
      startedSyncs = [],
    }: { loaded?: boolean; own?: boolean; startedSyncs?: StartedSync[] } = {},
  ) =>
    configureStore({
      reducer: {
        connectors: connectorsReducer,
        actionToast: actionToastReducer,
        notifications: notificationsReducer,
        preference: (state = { token: null }) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          startedSyncs,
          loading: !loaded,
          loaded,
          failed: false,
          catalog: [DRIVE],
          connections: loaded
            ? [
                ...(own
                  ? [
                      {
                        id: 'conn-1',
                        connector_key: 'google_drive',
                        status: 'connected',
                      },
                    ]
                  : []),
                { id: 'conn-gh', connector_key: 'github', status: 'connected' },
                ...extra,
              ]
            : [],
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

  type RenderOptions = {
    extra?: Record<string, unknown>[];
    initialConnectionId?: string;
    parts?: ConnectorDefinition[];
    loaded?: boolean;
    own?: boolean;
    startedSyncs?: StartedSync[];
    onConnect?: (connector: ConnectorDefinition, options?: unknown) => void;
  };
  const draw = async (
    connector: ConnectorDefinition | null,
    options: RenderOptions,
  ) => {
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/settings/connectors']}>
            <Routes>
              <Route
                path="/settings/connectors"
                element={
                  <ConnectionDrawer
                    connector={connector}
                    parts={options.parts}
                    initialConnectionId={options.initialConnectionId}
                    onClose={vi.fn()}
                    onConnect={options.onConnect ?? vi.fn()}
                  />
                }
              />
              <Route path="/settings/knowledge" element={<KnowledgePage />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };
  const render = async (
    connector: ConnectorDefinition | null = DRIVE,
    options: RenderOptions = {},
  ) => {
    store = makeStore(options.extra, options);
    await draw(connector, options);
  };

  const text = () => document.body.textContent ?? '';
  // The confirmation opens over the drawer (itself a dialog): the last one.
  const dialog = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="dialog"]'),
    ).pop()!;
  const inDialog = (label: string) =>
    Array.from(dialog().querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === label,
    )!;
  const menuItem = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((el) => el.textContent === label)!;

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === text)!;

  const accountRow = (name: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="list-row"]'),
    ).find((row) => row.textContent?.includes(name))!;

  // The row box (the li's one child) carries the selected state.
  const selectedIn = (row: HTMLElement) =>
    row.firstElementChild?.getAttribute('aria-current') === 'true';

  it('lists every account, the one shown below marked selected', async () => {
    connectors.getConnection.mockImplementation(async (id: string) => ({
      success: true,
      connection:
        id === 'conn-2'
          ? {
              ...DETAIL,
              id: 'conn-2',
              account_name: 'Max',
              sources: [{ ...DETAIL.sources[0], id: 'src-2', name: 'Notes' }],
            }
          : { ...DETAIL, account_name: 'Lena' },
    }));
    await render(DRIVE, {
      extra: [
        { id: 'conn-2', connector_key: 'google_drive', status: 'connected' },
      ],
      initialConnectionId: 'conn-2',
    });
    // Both accounts are rows; the one the panel opened for is selected and
    // its knowledge shows.
    expect(accountRow('Lena')).toBeTruthy();
    expect(selectedIn(accountRow('Max'))).toBe(true);
    expect(selectedIn(accountRow('Lena'))).toBe(false);
    expect(text()).toContain('Notes');
    expect(text()).not.toContain('Handbook');
    expect(
      document.body.querySelector(
        '[aria-label="settings.connectors.detail.accountPicker"]',
      ),
    ).toBeNull();

    // A row is picked by its stretched button; its ⋯ stays a sibling.
    const pick = accountRow('Lena').querySelector<HTMLButtonElement>(
      'button[data-account-select]',
    )!;
    expect(pick.closest('button')).toBe(pick);
    expect(
      pick.querySelector(
        '[aria-label="settings.connectors.detail.accountMenu"]',
      ),
    ).toBeNull();
    await act(async () => pick.click());
    expect(selectedIn(accountRow('Lena'))).toBe(true);
    expect(text()).toContain('Handbook');
    expect(text()).not.toContain('Notes');
  });

  it('shows a single account as a plain row, not a choice', async () => {
    await render();
    expect(
      document.body.querySelector('button[data-account-select]'),
    ).toBeNull();
    expect(document.body.querySelector('[aria-current="true"]')).toBeNull();
  });

  it('names the account like the Tools card, next to its status', async () => {
    await render();
    const row = accountRow('lena@example.com');
    expect(row.textContent).toContain(
      'settings.connectors.connectionStatus.connected',
    );
    expect(text()).not.toContain('settings.connectors.detail.connectedAs');
  });

  it('marks an account that needs signing in with Reconnect', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: { ...DETAIL, status: 'reconnect_needed' },
    });
    await render();
    const badge = accountRow('lena@example.com').querySelector(
      '[data-slot="badge"]',
    );
    expect(badge?.textContent).toBe('settings.connectors.status.reconnect');
    expect(text()).not.toContain(
      'settings.connectors.connectionStatus.reconnect_needed',
    );
  });

  describe('while it loads', () => {
    const loader = () =>
      document.body.querySelector('[data-slot="loading-state"]');
    const connectButton = () =>
      Array.from(document.body.querySelectorAll('button')).find(
        (b) => b.textContent === 'settings.connectors.status.connect',
      );

    it('shows a loading state, never "no account" and Connect', async () => {
      connectors.getConnection.mockReturnValue(new Promise(() => {}));
      await render();
      expect(loader()).not.toBeNull();
      expect(text()).not.toContain('settings.connectors.detail.noAccounts');
      expect(connectButton()).toBeUndefined();
    });

    it('waits for the connections list before saying there is none', async () => {
      await render(DRIVE, { loaded: false });
      expect(loader()).not.toBeNull();
      expect(text()).not.toContain('settings.connectors.detail.noAccounts');
      expect(connectButton()).toBeUndefined();
    });

    it("drops the last connector's accounts when another opens", async () => {
      await render();
      expect(text()).toContain('Handbook');
      connectors.getConnection.mockReturnValue(new Promise(() => {}));
      await draw({ ...DRIVE, key: 'github', name: 'GitHub' }, {});
      expect(text()).not.toContain('Handbook');
      expect(loader()).not.toBeNull();
      expect(connectButton()).toBeUndefined();
    });

    it('offers no Connect under the load error', async () => {
      connectors.getConnection.mockResolvedValue({ success: false });
      await render(DRIVE, { parts: [PART] });
      expect(text()).toContain('settings.connectors.detail.failed');
      expect(connectButton()).toBeUndefined();
      expect(text()).not.toContain('settings.connectors.detail.connectAnother');
    });
  });

  it('shows no dead accounts section while it needs admin setup', async () => {
    await render(
      { ...DRIVE, needs_setup: true, available: false },
      { own: false },
    );
    expect(text()).toContain('settings.connectors.status.needsAdminSetup');
    expect(text()).not.toContain('settings.connectors.detail.accounts');
    expect(text()).not.toContain('settings.connectors.detail.noAccounts');
  });

  it('puts the capability badges in the header', async () => {
    await render();
    const header = document.body.querySelector('[data-slot="panel-header"]')!;
    expect(header.textContent).toContain(
      'settings.connectors.capabilityPlain.sync',
    );
  });

  it('titles a tool by its service, without the account the server adds', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        tools: [{ ...DETAIL.tools[0], display_name: 'Google Drive · Work' }],
      },
    });
    await render();
    const heading = Array.from(document.body.querySelectorAll('h5')).map(
      (h) => h.textContent,
    );
    expect(heading).toContain('Google Drive');
    expect(text()).not.toContain('Google Drive · Work');
  });

  // The switch is the owner's "In my chats", the same one as on the tool's
  // card, not an on/off for everyone the tool is shared with.
  it('says in one line under Tools where Allow applies', async () => {
    await render();
    const tools = Array.from(document.body.querySelectorAll('h4')).find(
      (h) => h.textContent === 'settings.connectors.detail.tools',
    )!;
    expect(tools.parentElement!.parentElement!.textContent).toContain(
      'settings.connectors.detail.toolsHint',
    );
  });

  it('nests the action groups under the tool name as h6', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        tools: [
          {
            ...DETAIL.tools[0],
            actions: [
              {
                name: 'send_message',
                description: 'Send a message',
                access: 'write',
                permission: 'always',
              },
            ],
          },
        ],
      },
    });
    await render();
    expect(document.body.querySelectorAll('h6').length).toBeGreaterThan(0);
  });

  it('labels the tool switch "In my chats"', async () => {
    await render();
    const toggle = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.tools.useInMyChatsAria"]',
    )!;
    expect(toggle.getAttribute('role')).toBe('switch');
    const label = document.body.querySelector<HTMLLabelElement>(
      `label[for="${toggle.id}"]`,
    );
    expect(label?.textContent).toBe('settings.tools.inMyChats');
  });

  it('turns a tool on and off from its connection page', async () => {
    users.updateToolStatus.mockResolvedValue({ ok: true });
    await render();
    const toggle = document.body.querySelector<HTMLButtonElement>(
      '[aria-label="settings.tools.useInMyChatsAria"]',
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
      '[aria-label="settings.tools.useInMyChatsAria"]',
    )!;
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-checked')).toBe('true');
    expect(
      selectActionToast(
        store.getState() as Parameters<typeof selectActionToast>[0],
      )?.variant,
    ).toBe('destructive');
  });

  const openSourceMenu = async (name = 'Handbook') => {
    const trigger = accountRow(name).querySelector<HTMLButtonElement>(
      '[aria-label="settings.connectors.detail.sourceMenu"]',
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

  it('syncs a source now from its menu, once at a time', async () => {
    let answer: (value: unknown) => void = () => {};
    users.syncConnector.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    await render();
    await openSourceMenu();
    expect(menuLabels()).toEqual([
      'settings.connectors.detail.syncNow',
      'settings.connectors.openInKnowledge',
    ]);
    await act(async () =>
      menuItem('settings.connectors.detail.syncNow').click(),
    );
    expect(users.syncConnector).toHaveBeenCalledWith('src-1', null);
    expect(users.syncSource).not.toHaveBeenCalled();
    // Pending: a spinner on the row, and no second start.
    expect(
      accountRow('Handbook').querySelector('[data-slot="spinner"]'),
    ).not.toBeNull();
    await openSourceMenu();
    expect(
      menuItem('settings.connectors.detail.syncNow').hasAttribute(
        'data-disabled',
      ),
    ).toBe(true);
    await act(async () => {
      answer({ json: async () => ({ success: true }) });
    });
    expect(
      accountRow('Handbook').querySelector('[data-slot="spinner"]'),
    ).toBeNull();
    expect(users.syncConnector).toHaveBeenCalledTimes(1);
    expect(
      selectActionToast(
        store.getState() as Parameters<typeof selectActionToast>[0],
      )?.variant,
    ).toBe('success');
  });

  it('offers no Sync now on a source converted to a wiki', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        sources: [{ ...DETAIL.sources[0], kind: 'wiki' }],
      },
    });
    await render();
    await openSourceMenu();
    expect(menuLabels()).toEqual(['settings.connectors.openInKnowledge']);
  });

  // The wording of every refusal is syncRefusal's (syncRefusal.test.ts).
  it.each([
    [
      'a coded refusal in its own words',
      () =>
        users.syncConnector.mockResolvedValue({
          json: async () => ({
            success: false,
            code: 'wiki',
            error: 'English text',
          }),
        }),
      'settings.connectors.detail.syncRefusedWiki',
    ],
    [
      'a failed request as the localized failure',
      () => users.syncConnector.mockRejectedValue(new Error('offline')),
      'settings.connectors.detail.syncFailed',
    ],
  ])('toasts %s', async (_, answer, message) => {
    answer();
    await render();
    await openSourceMenu();
    await act(async () =>
      menuItem('settings.connectors.detail.syncNow').click(),
    );
    const toast = selectActionToast(
      store.getState() as Parameters<typeof selectActionToast>[0],
    );
    expect(toast?.variant).toBe('destructive');
    expect(toast?.message).toBe(message);
  });

  it('offers no Sync now while the connection is not connected', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        status: 'reconnect_needed',
        sources: [{ ...DETAIL.sources[0], sync_state: 'paused_reconnect' }],
      },
    });
    await render(DRIVE, {
      own: false,
      extra: [
        {
          id: 'conn-1',
          connector_key: 'google_drive',
          status: 'reconnect_needed',
        },
      ],
    });
    await openSourceMenu();
    expect(menuLabels()).toEqual(['settings.connectors.openInKnowledge']);
    expect(text()).toContain('settings.connectors.detail.paused');
  });

  it('opens a source in Knowledge from its row', async () => {
    await render();
    const open = accountRow('Handbook').querySelector<HTMLButtonElement>(
      'button[data-source-open]',
    )!;
    expect(open.textContent).toBe('Handbook');
    // It truncates, so the full name is on the node.
    expect(open.title).toBe('Handbook');
    await act(async () => open.click());
    expect(text()).toContain('KNOWLEDGE?source=src-1');
  });

  it('opens a source in Knowledge from its menu', async () => {
    await render();
    await openSourceMenu();
    await act(async () =>
      menuItem('settings.connectors.openInKnowledge').click(),
    );
    expect(text()).toContain('KNOWLEDGE?source=src-1');
  });

  it('says how a source stays current, the way its card does', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: {
        ...DETAIL,
        sources: [
          { ...DETAIL.sources[0], last_sync: '2026-10-20T10:00:00Z' },
          {
            ...DETAIL.sources[0],
            id: 'src-2',
            name: 'Notes',
            sync_frequency: 'never',
            last_sync: '2026-10-20T10:00:00Z',
          },
        ],
      },
    });
    await render();
    expect(accountRow('Handbook').textContent).toContain(
      'settings.sources.website.synced',
    );
    expect(accountRow('Notes').textContent).toContain(
      'settings.connectors.detail.lastSync',
    );
  });

  describe('knowledge from this connection', () => {
    const startedIds = () =>
      selectStartedSyncs(
        store.getState() as Parameters<typeof selectStartedSyncs>[0],
      ).map((sync) => sync.id);
    const started = (minutesAgo = 0, id = 'src-new', name = 'Contracts') => ({
      id,
      name,
      connectionId: 'conn-1',
      startedAt: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    });
    /** A source's first ingest ending, as the event stream says it. */
    const ingestEnded = (
      id: string,
      outcome: 'completed' | 'failed' = 'completed',
    ) =>
      act(async () => {
        store.dispatch(
          sseEventReceived({
            id: `ev-${id}-${outcome}`,
            type: `source.ingest.${outcome}`,
            scope: { kind: 'source', id },
            payload: {},
          }),
        );
      });

    it('offers Sync content in an empty state, with no header link', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, sources: [] },
      });
      const onConnect = vi.fn();
      await render(DRIVE, { onConnect });
      const empty = document.body.querySelector<HTMLElement>(
        '[data-slot="empty-state"]',
      )!;
      expect(empty.dataset.size).toBe('sm');
      expect(empty.textContent).toContain(
        'settings.connectors.detail.noSources',
      );
      expect(empty.textContent).toContain(
        'settings.connectors.detail.noSourcesHint',
      );
      expect(button('settings.connectors.detail.syncMore')).toBeUndefined();
      const sync = button('settings.connectors.syncContent');
      expect(sync.dataset.variant).toBe('outline');
      await act(async () => sync.click());
      expect(onConnect).toHaveBeenCalledWith(DRIVE, {
        mode: 'sync',
        connectionId: 'conn-1',
      });
    });

    it('links Sync more content once there is a source', async () => {
      await render();
      expect(button('settings.connectors.detail.syncMore')).toBeDefined();
      expect(button('settings.connectors.syncContent')).toBeUndefined();
    });

    it('lists a sync it started as indexing until the server lists it', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, sources: [] },
      });
      await render(DRIVE, {
        startedSyncs: [
          started(),
          // Another account's sync stays with that account.
          {
            ...started(0, 'src-elsewhere', 'Elsewhere'),
            connectionId: 'conn-9',
          },
        ],
      });
      const row = accountRow('Contracts');
      expect(row.textContent).toContain('settings.connectors.detail.indexing');
      expect(row.textContent).toContain(
        'settings.connectors.detail.firstSyncStarted',
      );
      // Not in Knowledge yet: nothing to open or sync.
      expect(row.querySelector('button')).toBeNull();
      expect(text()).not.toContain('Elsewhere');
      // Not "nothing synced" meanwhile; Sync more is offered.
      expect(
        document.body.querySelector('[data-slot="empty-state"]'),
      ).toBeNull();
      expect(button('settings.connectors.detail.syncMore')).toBeDefined();
      // Its ingest finishing reloads the list, which now has it.
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: {
          ...DETAIL,
          sources: [{ ...DETAIL.sources[0], id: 'src-new', name: 'Contracts' }],
        },
      });
      connectors.listConnections.mockResolvedValueOnce({
        success: true,
        connections: [
          { id: 'conn-1', connector_key: 'google_drive', status: 'connected' },
        ],
      });
      const calls = connectors.getConnection.mock.calls.length;
      await ingestEnded('src-new');
      expect(connectors.getConnection.mock.calls.length).toBeGreaterThan(calls);
      expect(accountRow('Contracts').textContent).not.toContain(
        'settings.connectors.detail.indexing',
      );
      // Listed now, it is no longer kept as started.
      expect(startedIds()).toEqual(['src-elsewhere']);
    });

    const renderUnlisted = async () => {
      // Never listed: the source was deleted, or can't be listed.
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, sources: [] },
      });
      connectors.listConnections.mockResolvedValue({
        success: true,
        connections: [
          {
            id: 'conn-1',
            connector_key: 'google_drive',
            status: 'connected',
          },
        ],
      });
      await render(DRIVE, { startedSyncs: [started()] });
      expect(text()).toContain('Contracts');
    };

    it('stops showing a sync once its ingest completed, listed or not', async () => {
      await renderUnlisted();
      await ingestEnded('src-new');
      // The account still shows, without the sync.
      expect(text()).toContain('lena@example.com');
      expect(text()).not.toContain('Contracts');
      expect(text()).not.toContain('settings.connectors.detail.indexing');
      // A finished one the reload still doesn't list is forgotten, so the
      // next drawer doesn't reload for it again.
      expect(startedIds()).toEqual([]);
    });

    it('shows a failed first sync as failed until it is dismissed', async () => {
      await renderUnlisted();
      await ingestEnded('src-new', 'failed');
      const row = accountRow('Contracts');
      expect(row.textContent).toContain('settings.sources.ingestFailed');
      expect(row.textContent).not.toContain(
        'settings.connectors.detail.indexing',
      );
      expect(startedIds()).toEqual(['src-new']);
      const dismiss = row.querySelector<HTMLButtonElement>(
        'button[aria-label^="settings.connectors.detail.dismissFailedSync"]',
      )!;
      await act(async () => dismiss.click());
      expect(startedIds()).toEqual([]);
      expect(text()).not.toContain('Contracts');
      expect(text()).toContain('lena@example.com');
    });

    it('lists the indexing syncs before the failed ones, whatever their start order', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, sources: [] },
      });
      await render(DRIVE, {
        startedSyncs: [
          started(0, 'src-a', 'Alpha'),
          started(0, 'src-b', 'Beta'),
          started(0, 'src-c', 'Gamma'),
        ],
      });
      await ingestEnded('src-a', 'failed');
      const rows = Array.from(
        document.body.querySelectorAll<HTMLElement>('[data-slot="list-row"]'),
      )
        .map((row) => row.textContent ?? '')
        .filter((row) => /Alpha|Beta|Gamma/.test(row));
      expect(rows.map((row) => row.match(/Alpha|Beta|Gamma/)?.[0])).toEqual([
        'Beta',
        'Gamma',
        'Alpha',
      ]);
      expect(rows[2]).toContain('settings.sources.ingestFailed');
      expect(rows[0]).toContain('settings.connectors.detail.indexing');
    });

    it('gives up on a sync with no word on its ingest after 15 minutes', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, sources: [] },
      });
      await render(DRIVE, { startedSyncs: [started(16)] });
      expect(text()).not.toContain('Contracts');
      expect(text()).not.toContain('settings.connectors.detail.indexing');
    });

    it('gives up 15 minutes after a sync started while it was mounted', async () => {
      vi.useFakeTimers({ now: new Date('2026-10-23T10:00:00Z') });
      try {
        connectors.getConnection.mockResolvedValue({
          success: true,
          connection: { ...DETAIL, sources: [] },
        });
        await render(DRIVE);
        await act(async () => vi.advanceTimersByTime(5 * 60_000));
        await act(async () => store.dispatch(syncStarted([started()])));
        expect(text()).toContain('Contracts');
        await act(async () => vi.advanceTimersByTime(15 * 60_000 - 1_000));
        expect(text()).toContain('Contracts');
        await act(async () => vi.advanceTimersByTime(2_000));
        expect(text()).not.toContain('Contracts');
      } finally {
        vi.useRealTimers();
      }
    });

    it('does nothing about a finished sync while closed', async () => {
      await render(null, { startedSyncs: [started()] });
      const loads = connectors.listConnections.mock.calls.length;
      const reads = connectors.getConnection.mock.calls.length;
      await ingestEnded('src-new');
      expect(connectors.listConnections.mock.calls.length).toBe(loads);
      expect(connectors.getConnection.mock.calls.length).toBe(reads);
      // Kept for the drawer that opens on its account.
      expect(startedIds()).toEqual(['src-new']);
    });

    it("leaves another account's finished sync to that account", async () => {
      await render(DRIVE, {
        startedSyncs: [{ ...started(), connectionId: 'conn-9' }],
      });
      const loads = connectors.listConnections.mock.calls.length;
      const reads = connectors.getConnection.mock.calls.length;
      await ingestEnded('src-new');
      expect(connectors.listConnections.mock.calls.length).toBe(loads);
      expect(connectors.getConnection.mock.calls.length).toBe(reads);
      expect(startedIds()).toEqual(['src-new']);
    });
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
    expect(text).toContain('lena@example.com');
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
    expect(text).toContain('lena@example.com');
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

  describe('account menu', () => {
    it('keeps Disconnect a normal item and puts Remove after a rule', async () => {
      await render();
      await openAccountMenu();
      const disconnect = menuItem('settings.connectors.detail.disconnect');
      const remove = menuItem('settings.connectors.detail.remove');
      expect(disconnect.getAttribute('data-variant')).not.toBe('destructive');
      expect(remove.getAttribute('data-variant')).toBe('destructive');
      expect(remove.previousElementSibling?.getAttribute('data-slot')).toBe(
        'dropdown-menu-separator',
      );
    });

    it('disconnects the named account, pending, and keeps a failure in the modal', async () => {
      let finish: (value: unknown) => void = () => {};
      connectors.disconnect.mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, account_name: 'Alerts bot' },
      });
      await render();
      await openAccountMenu();
      await act(async () =>
        menuItem('settings.connectors.detail.disconnect').click(),
      );
      expect(dialog().textContent).toContain(
        'settings.connectors.disconnect.title(Alerts bot)',
      );
      const submit = inDialog('settings.connectors.detail.disconnect');
      // Nothing is deleted, so the submit is the primary, not red.
      expect(submit.getAttribute('data-variant')).toBe('default');
      await act(async () => submit.click());
      expect(connectors.disconnect).toHaveBeenCalledWith('conn-1', null);
      expect(submit.getAttribute('aria-busy')).toBe('true');
      await act(async () => finish({ success: false }));
      expect(dialog().textContent).toContain(
        'settings.connectors.disconnect.failed',
      );
      expect(
        selectActionToast(
          store.getState() as Parameters<typeof selectActionToast>[0],
        ),
      ).toBeFalsy();
    });

    const disconnectBody = async (detail: Record<string, unknown>) => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...DETAIL, ...detail },
      });
      await render();
      await openAccountMenu();
      await act(async () =>
        menuItem('settings.connectors.detail.disconnect').click(),
      );
      return dialog().textContent ?? '';
    };

    it('says what a disconnect stops, from what the account has', async () => {
      expect(await disconnectBody({})).toContain(
        'settings.connectors.disconnect.bodyBoth',
      );
    });

    it('does not mention tools for a sync-only account', async () => {
      const body = await disconnectBody({ tools: [] });
      expect(body).toContain('settings.connectors.disconnect.bodySources');
      expect(body).not.toContain('settings.connectors.disconnect.bodyBoth');
    });

    it('mentions only tools for a tool-only account', async () => {
      expect(await disconnectBody({ sources: [] })).toContain(
        'settings.connectors.disconnect.bodyTools',
      );
    });

    it('says only the sign-in goes for an account with neither', async () => {
      expect(await disconnectBody({ sources: [], tools: [] })).toContain(
        'settings.connectors.disconnect.bodyNone',
      );
    });

    it('names the account in Remove, Keep before Delete in both groups', async () => {
      await render();
      await openAccountMenu();
      await act(async () =>
        menuItem('settings.connectors.detail.remove').click(),
      );
      expect(dialog().textContent).toContain(
        'settings.connectors.remove.title(lena@example.com)',
      );
      const groups = Array.from(
        dialog().querySelectorAll('[data-slot="toggle-group"]'),
      ).map((group) =>
        Array.from(group.querySelectorAll('button')).map((b) => b.textContent),
      );
      expect(groups).toEqual([
        [
          'settings.connectors.remove.keepSources',
          'settings.connectors.remove.deleteSources',
        ],
        [
          'settings.connectors.remove.keepTools',
          'settings.connectors.remove.deleteTools',
        ],
      ]);
      // Each keep/delete choice is alone under its label: it fills the row.
      for (const group of dialog().querySelectorAll(
        '[data-slot="toggle-group"]',
      )) {
        expect(group.classList.contains('w-full')).toBe(true);
      }
    });

    it.each([
      // The removed account's sync goes with its sources; another's stays.
      ['deleteSources', ['src-other']],
      ['keepSources', ['src-new', 'src-other']],
    ])(
      'removing an account (%s) forgets the syncs whose sources went with it',
      async (choice, kept) => {
        connectors.remove.mockResolvedValue({ success: true });
        await render(DRIVE, {
          startedSyncs: [
            {
              id: 'src-new',
              name: 'Contracts',
              connectionId: 'conn-1',
              startedAt: new Date().toISOString(),
            },
            {
              id: 'src-other',
              name: 'Elsewhere',
              connectionId: 'conn-9',
              startedAt: new Date().toISOString(),
            },
          ],
        });
        await openAccountMenu();
        await act(async () =>
          menuItem('settings.connectors.detail.remove').click(),
        );
        await act(async () =>
          inDialog(`settings.connectors.remove.${choice}`).click(),
        );
        await act(async () =>
          inDialog('settings.connectors.detail.remove').click(),
        );
        expect(connectors.remove).toHaveBeenCalled();
        const left = selectStartedSyncs(
          store.getState() as Parameters<typeof selectStartedSyncs>[0],
        ).map((sync) => sync.id);
        expect(left).toEqual(kept);
      },
    );

    it("names a part's account by its own service when it has no name", async () => {
      connectors.getConnection.mockImplementation(async (id: string) => ({
        success: true,
        connection:
          id === 'conn-p'
            ? {
                ...DETAIL,
                id: 'conn-p',
                connector_key: 'mcp:atlassian',
                auth_kind: 'api_key',
                account_label: '…9QkX',
                sources: [],
              }
            : DETAIL,
      }));
      await render(DRIVE, {
        parts: [PART],
        extra: [
          { id: 'conn-p', connector_key: 'mcp:atlassian', status: 'connected' },
        ],
      });
      const menus = document.body.querySelectorAll<HTMLButtonElement>(
        '[aria-label="settings.connectors.detail.accountMenu"]',
      );
      await act(async () => {
        menus[1].dispatchEvent(
          new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
        );
        menus[1].click();
      });
      await act(async () =>
        menuItem('settings.connectors.detail.remove').click(),
      );
      expect(dialog().textContent).toContain(
        'settings.connectors.remove.title(Jira & Confluence)',
      );
    });
  });

  describe('parts', () => {
    const connectIn = (section: Element) =>
      Array.from(section.querySelectorAll('button')).find(
        (b) => b.textContent === 'settings.connectors.status.connect',
      );
    const section = (name: string) =>
      Array.from(document.body.querySelectorAll('section')).find(
        (el) => el.querySelector('h3')?.textContent === name,
      )!;

    it('is a sibling section with the parent-size Connect', async () => {
      await render(DRIVE, { parts: [PART] });
      // With parts, each service is headed by its own name.
      expect(section('Google Drive')).toBeTruthy();
      const part = section('Jira & Confluence');
      expect(part.textContent).toContain('settings.connectors.descriptions.');
      const connect = connectIn(part)!;
      expect(connect.closest('[data-slot="empty-state"]')).not.toBeNull();
      expect(connect.getAttribute('data-size')).toBe('default');
      // The union of what they do sits in the header, not per part.
      const header = document.body.querySelector('[data-slot="panel-header"]')!;
      expect(header.textContent).toContain(
        'settings.connectors.capabilityPlain.write',
      );
      expect(part.textContent).not.toContain(
        'settings.connectors.capabilityPlain.write',
      );
    });

    it('offers another account once the part has one', async () => {
      connectors.getConnection.mockImplementation(async (id: string) => ({
        success: true,
        connection:
          id === 'conn-p'
            ? { ...DETAIL, id: 'conn-p', connector_key: 'mcp:atlassian' }
            : DETAIL,
      }));
      await render(DRIVE, {
        parts: [PART],
        extra: [
          { id: 'conn-p', connector_key: 'mcp:atlassian', status: 'connected' },
        ],
      });
      expect(section('Jira & Confluence').textContent).toContain(
        'settings.connectors.detail.connectAnother',
      );
    });
  });

  it('adds back the tool of an auto-tools connection after it was deleted', async () => {
    connectors.setup.mockReset();
    connectors.setup.mockResolvedValue({ success: true, tools: [] });
    const TELEGRAM = {
      ...DRIVE,
      key: 'google_drive',
      name: 'Telegram',
      auth_kind: 'api_key',
      capabilities: ['write'],
      setup: { tools: 'auto', sync: 'off' },
      sync_ingestor: null,
      tool_templates: ['telegram'],
    } as unknown as ConnectorDefinition;
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: { ...DETAIL, sources: [], tools: [] },
    });
    await render(TELEGRAM);
    await act(async () =>
      button('settings.connectors.detail.addTools').click(),
    );
    expect(connectors.setup).toHaveBeenCalledWith(
      'conn-1',
      { create_tools: true },
      null,
    );
  });

  describe('MCP preset whose tool was deleted', () => {
    const NOTION = {
      ...DRIVE,
      key: 'mcp:notion',
      name: 'Notion',
      icon: 'notion',
      publisher: 'preset',
      auth_kind: 'mcp_oauth',
      capabilities: ['read', 'write'],
      setup: { tools: 'auto', sync: 'off' },
      sync_ingestor: null,
      tool_templates: ['mcp_tool'],
      mcp_url: 'https://mcp.notion.com/mcp',
    } as unknown as ConnectorDefinition;
    const NO_TOOLS = {
      ...DETAIL,
      connector_key: 'mcp:notion',
      name: 'Notion',
      auth_kind: 'mcp_oauth',
      sources: [],
      tools: [],
    };
    const ACCOUNT = {
      own: false,
      extra: [
        { id: 'conn-1', connector_key: 'mcp:notion', status: 'connected' },
      ],
    };
    const toolsSection = () =>
      button('settings.connectors.detail.addTools').closest('section')!;

    beforeEach(() => {
      connectors.setup.mockReset();
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: NO_TOOLS,
      });
      // Adding reloads the connections list; the account is still there.
      connectors.listConnections.mockResolvedValue({
        success: true,
        connections: ACCOUNT.extra,
      });
    });

    afterEach(() => {
      connectors.listConnections.mockResolvedValue({
        success: true,
        connections: [],
      });
    });

    it('offers Add tools and rebuilds the tool from the sign-in', async () => {
      connectors.setup.mockResolvedValue({ success: true, tools: [] });
      await render(NOTION, ACCOUNT);
      const loads = connectors.getConnection.mock.calls.length;
      await act(async () =>
        button('settings.connectors.detail.addTools').click(),
      );
      expect(connectors.setup).toHaveBeenCalledWith(
        'conn-1',
        { create_tools: true },
        null,
      );
      // The page reloads the connection, with its new tool.
      expect(connectors.getConnection.mock.calls.length).toBeGreaterThan(loads);
    });

    it('shows a failure in the tools section, not only as a toast', async () => {
      connectors.setup.mockResolvedValue({
        success: false,
        code: 'tools_unavailable',
      });
      await render(NOTION, ACCOUNT);
      await act(async () =>
        button('settings.connectors.detail.addTools').click(),
      );
      const alert = toolsSection().querySelector('[role="alert"]');
      expect(alert?.textContent).toBe(
        'settings.connectors.detail.toolsUnavailable(Notion)',
      );
      expect(
        button('settings.connectors.detail.addTools').hasAttribute('aria-busy'),
      ).toBe(false);
    });

    it('clears the failure when adding again succeeds', async () => {
      connectors.setup.mockResolvedValueOnce({ success: false });
      await render(NOTION, ACCOUNT);
      await act(async () =>
        button('settings.connectors.detail.addTools').click(),
      );
      expect(toolsSection().querySelector('[role="alert"]')?.textContent).toBe(
        'settings.connectors.detail.addToolsFailed',
      );
      connectors.setup.mockResolvedValueOnce({ success: true, tools: [] });
      await act(async () =>
        button('settings.connectors.detail.addTools').click(),
      );
      expect(toolsSection().querySelector('[role="alert"]')).toBeNull();
    });

    it('is not offered while the account needs signing in again', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...NO_TOOLS, status: 'reconnect_needed' },
      });
      await render(NOTION, ACCOUNT);
      expect(button('settings.connectors.detail.addTools')).toBeUndefined();
    });
  });

  it('offers no Add tools for a custom MCP server', async () => {
    connectors.getConnection.mockResolvedValue({
      success: true,
      connection: { ...DETAIL, sources: [], tools: [] },
    });
    await render({
      ...DRIVE,
      publisher: 'custom',
      setup: { tools: 'ask', sync: 'off' },
      sync_ingestor: null,
      tool_templates: ['mcp_tool'],
    } as unknown as ConnectorDefinition);
    expect(button('settings.connectors.detail.addTools')).toBeUndefined();
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
      connectors.setWrites.mockReset();
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: TOKEN_DETAIL,
      });
    });

    it('names a token connection by its account, not as a key hint', async () => {
      await render(GITHUB);
      expect(document.body.textContent).toContain('octocat');
      expect(document.body.textContent).not.toContain(
        'settings.connectors.detail.keyEnding',
      );
    });

    const GITHUB_TOOL = {
      id: 'tool-gh',
      name: 'mcp_tool',
      display_name: 'GitHub',
      status: true,
      credential_mode: 'owner',
      actions: [],
    };
    const writesSwitch = () =>
      document.body.querySelector<HTMLButtonElement>('#writes-conn-1');

    it('switches a connection between reading and making changes', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...TOKEN_DETAIL, tools: [GITHUB_TOOL], writes: false },
      });
      connectors.setWrites.mockResolvedValue({ success: true, writes: true });
      await render({ ...GITHUB, writes_allowed: true });
      expect(writesSwitch()!.getAttribute('aria-checked')).toBe('false');
      // A row inside the tool's permissions card, not a second box above it.
      expect(writesSwitch()!.closest('[data-slot="card"]')).not.toBeNull();
      const loads = connectors.getConnection.mock.calls.length;
      await act(async () => writesSwitch()!.click());
      expect(connectors.setWrites).toHaveBeenCalledWith('conn-1', true, null);
      // The page reloads the connection, with the new endpoint's actions.
      expect(connectors.getConnection.mock.calls.length).toBeGreaterThan(loads);
    });

    it('says when switching failed', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...TOKEN_DETAIL, tools: [GITHUB_TOOL], writes: false },
      });
      connectors.setWrites.mockResolvedValue({
        success: false,
        code: 'writes_forbidden',
      });
      await render({ ...GITHUB, writes_allowed: true });
      await act(async () => writesSwitch()!.click());
      const toast = selectActionToast(
        store.getState() as Parameters<typeof selectActionToast>[0],
      );
      expect(toast?.variant).toBe('destructive');
      expect(toast?.message).toBe('settings.connectors.github.writesForbidden');
    });

    it('hides the switch when an admin turned changes off', async () => {
      connectors.getConnection.mockResolvedValue({
        success: true,
        connection: { ...TOKEN_DETAIL, tools: [GITHUB_TOOL], writes: false },
      });
      await render({ ...GITHUB, writes_allowed: false });
      expect(writesSwitch()).toBeNull();
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
