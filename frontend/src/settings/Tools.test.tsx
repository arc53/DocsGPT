import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

// The store's slices the page reads; each test sets the connections it needs.
const reduxState = {
  preference: { token: 'token' },
  connectors: {
    enabled: true,
    catalog: [] as unknown[],
    connections: [] as unknown[],
    loaded: true,
    loading: false,
    failed: false,
  },
};
const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) => selector(reduxState),
  useDispatch: () => dispatch,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const { interpolation: _i, ...rest } = opts ?? {};
      void _i;
      return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
    },
  }),
}));

vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useLoaderState: (initial: boolean) => useState(initial),
}));

// The menu is a Radix dropdown; the tests only need its options.
vi.mock('../components/ui/dropdown-menu', () => ({
  ActionMenu: ({
    options,
  }: {
    options: { label: string; onClick: () => void }[];
  }) => (
    <div data-testid="menu">
      {options.map((o) => (
        <button key={o.label} type="button" onClick={o.onClick}>
          {o.label}
        </button>
      ))}
    </div>
  ),
}));

const toolConfigProps = vi.fn();
vi.mock('./ToolConfig', () => ({
  default: (props: unknown) => {
    toolConfigProps(props);
    return <div data-testid="tool-config" />;
  },
}));
vi.mock('./RemoteDeviceConfig', () => ({ default: () => null }));
vi.mock('../modals/AddToolModal', () => ({ default: () => null }));
const confirm = vi.hoisted(() => ({
  props: null as null | {
    modalState: string;
    handleSubmit: () => void | Promise<unknown>;
    error?: string;
  },
}));
vi.mock('../modals/ConfirmationModal', () => ({
  default: (props: {
    modalState: string;
    handleSubmit: () => void | Promise<unknown>;
    error?: string;
  }) => {
    confirm.props = props;
    return null;
  },
}));
const mcpModalProps = vi.fn();
vi.mock('../modals/MCPServerModal', () => ({
  default: (props: unknown) => {
    mcpModalProps(props);
    return null;
  },
}));
const shareModalProps = vi.fn();
vi.mock('../teams/ShareToTeamModal', () => ({
  default: (props: unknown) => {
    shareModalProps(props);
    return null;
  },
}));
vi.mock('../api/services/devicesService', () => ({ default: {} }));

const reconnect = vi.fn();
vi.mock('../connectors/SignInAgainNotice', () => ({
  useSignInAgain: () => ({ reconnect, modals: null }),
}));

const getUserTools = vi.fn();
const updateToolStatus = vi.fn();
const deleteTool = vi.fn();
const mcpStatuses = vi.hoisted(() => ({ value: {} as Record<string, string> }));
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: (...args: unknown[]) => getUserTools(...args),
    getMCPAuthStatus: () =>
      Promise.resolve({
        json: () =>
          Promise.resolve({ success: true, statuses: mcpStatuses.value }),
      }),
    updateToolStatus: (...args: unknown[]) => updateToolStatus(...args),
    deleteTool: (...args: unknown[]) => deleteTool(...args),
  },
}));

import Tools from './Tools';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const baseTool = {
  name: 'mcp_tool',
  displayName: 'Carrier Rates MCP',
  description: 'Live rates',
  config: { server_url: 'https://mcp.example.com/sse', auth_type: 'api_key' },
  actions: [],
};

const ownTool = {
  ...baseTool,
  id: 'own',
  displayName: 'own',
  status: true,
  in_chat: true,
  access: 'owner',
  allowed_actions: [
    'delete',
    'edit',
    'edit_credentials',
    'manage_settings',
    'share',
    'use',
    'use_in_own',
  ],
};
const editorTool = {
  ...baseTool,
  id: 'ed',
  displayName: 'ed',
  status: true,
  in_chat: false,
  ownership: 'team',
  team_access: 'editor',
  access: 'editor',
  allowed_actions: ['edit', 'edit_credentials', 'use', 'use_in_own'],
  shared_via: 'Logistics',
  owner_label: 'lena@example.com',
};
const viewerTool = {
  ...baseTool,
  id: 'vw',
  displayName: 'vw',
  status: true,
  in_chat: false,
  ownership: 'team',
  team_access: 'viewer',
  access: 'viewer',
  allowed_actions: ['use'],
};

const jsonResponse = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

const renderTools = (root: Root) =>
  act(async () => {
    root.render(
      <MemoryRouter initialEntries={['/settings/tools']}>
        <Routes>
          <Route path="/settings/tools" element={<Tools />} />
          <Route path="/settings/connectors" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );
  });

describe('Tools', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    reduxState.connectors.catalog = [];
    reduxState.connectors.connections = [];
    mcpStatuses.value = {};
    dispatch.mockReset();
    getUserTools.mockReset();
    updateToolStatus.mockReset();
    toolConfigProps.mockReset();
    mcpModalProps.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (tools: unknown[]) => {
    getUserTools.mockImplementation(() => jsonResponse({ tools }));
    await renderTools(root);
  };

  const card = (name: string) =>
    Array.from(container.querySelectorAll<HTMLElement>('[data-slot="card"]'))
      .filter((c) => c.querySelector('[data-testid="menu"]'))
      .find(
        (c) =>
          c.querySelector('[data-slot="card-title"]')?.textContent === name,
      )!;
  const menuLabels = (id: string) =>
    Array.from(card(id).querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );
  const switchOf = (id: string) =>
    card(id).querySelector<HTMLButtonElement>('[role="switch"]')!;

  // A safety net: 48 per page, so a usual list never splits.
  it('pages past 48 tools, and a search starts on page 1', async () => {
    const many = Array.from({ length: 50 }, (_, i) => ({
      ...ownTool,
      id: `t${i}`,
      displayName: `tool ${i}`,
    }));
    await render(many);
    const cards = () =>
      container.querySelectorAll('[data-slot="card"] [data-testid="menu"]');
    expect(cards()).toHaveLength(48);
    const pager = container.querySelector('[data-slot="pagination-full"]')!;
    expect(pager.textContent).toContain('settings.tools.pageRange');
    await act(async () =>
      pager
        .querySelector<HTMLButtonElement>(
          '[aria-label=\'pagination.goToPage:{"page":2}\']',
        )!
        .click(),
    );
    expect(cards()).toHaveLength(2);
    const input =
      container.querySelector<HTMLInputElement>('#tool-search-input')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, 'tool');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(cards()).toHaveLength(48);
  });

  it('draws no pager for 48 tools or fewer', async () => {
    await render([ownTool, editorTool, viewerTool]);
    expect(container.querySelector('[data-slot="pagination"]')).toBeNull();
  });

  it('shows Edit, Reconnect, Share and Delete to the owner', async () => {
    await render([ownTool]);
    expect(menuLabels('own')).toEqual([
      'settings.tools.edit',
      'settings.tools.reconnect',
      'settings.tools.shareWithTeam',
      'settings.tools.delete',
    ]);
  });

  // ConfirmationModal stays pending on the returned promise and keeps a
  // failure in the dialog.
  const confirmDelete = async () => {
    await act(async () => {
      Array.from(
        card('own').querySelectorAll<HTMLButtonElement>(
          '[data-testid="menu"] button',
        ),
      )
        .find((b) => b.textContent === 'settings.tools.delete')!
        .click();
    });
    expect(confirm.props!.modalState).toBe('ACTIVE');
    let result: void | Promise<unknown>;
    await act(async () => {
      result = confirm.props!.handleSubmit();
      if (result) result.catch(() => undefined);
    });
    expect(result!).toBeInstanceOf(Promise);
    return result!;
  };

  it('keeps a refused delete in the dialog, not a toast', async () => {
    deleteTool.mockResolvedValue({ ok: false, status: 403 });
    await render([ownTool]);
    await expect(confirmDelete()).rejects.toThrow();
    expect(confirm.props!.error).toBe('settings.tools.deleteFailed');
    expect(dispatch).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: 'actionToast/showActionToast' }),
    );
  });

  it('returns the delete promise and reloads the tools on success', async () => {
    deleteTool.mockResolvedValue({ ok: true });
    await render([ownTool]);
    const calls = getUserTools.mock.calls.length;
    await expect(confirmDelete()).resolves.toBeUndefined();
    expect(deleteTool).toHaveBeenCalledWith({ id: 'own' }, 'token');
    expect(getUserTools.mock.calls.length).toBeGreaterThan(calls);
  });

  it('shows Edit and Reconnect to an editor', async () => {
    await render([editorTool]);
    expect(menuLabels('ed')).toEqual([
      'settings.tools.edit',
      'settings.tools.reconnect',
    ]);
  });

  it("hides Reconnect from an editor of an OAuth server (the sign-in is the owner's)", async () => {
    const oauthConfig = { ...baseTool.config, auth_type: 'oauth' };
    await render([
      { ...editorTool, config: oauthConfig },
      { ...ownTool, config: oauthConfig },
    ]);
    expect(menuLabels('ed')).toEqual(['settings.tools.edit']);
    expect(menuLabels('own')).toContain('settings.tools.reconnect');
  });

  it('shows only View to a viewer, which opens the config read-only', async () => {
    await render([viewerTool]);
    expect(menuLabels('vw')).toEqual(['settings.tools.view']);
    await act(async () => {
      (
        card('vw').querySelector('[data-testid="menu"] button') as HTMLElement
      ).click();
    });
    expect(container.querySelector('[data-testid="tool-config"]')).not.toBe(
      null,
    );
  });

  it('passes the tool owner and role to the Reconnect modal', async () => {
    await render([editorTool]);
    const reconnect = Array.from(
      card('ed').querySelectorAll<HTMLButtonElement>(
        '[data-testid="menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.tools.reconnect')!;
    await act(async () => reconnect.click());
    const last = mcpModalProps.mock.calls.at(-1)![0] as {
      server: Record<string, unknown>;
    };
    expect(last.server).toMatchObject({
      id: 'ed',
      displayName: 'ed',
      access: 'editor',
      owner_label: 'lena@example.com',
    });
  });

  // The caller's own "In my chats" switch stays on the tile, named for
  // screen readers only: the tile shows no label text beside it.
  it('keeps the In my chats switch, bound to in_chat, without its label text', async () => {
    await render([ownTool, editorTool]);
    const sw = switchOf('ed');
    expect(sw.getAttribute('aria-checked')).toBe('false');
    expect(switchOf('own').getAttribute('aria-checked')).toBe('true');
    expect(sw.getAttribute('aria-label')).toBe(
      'settings.tools.useInMyChatsAria:{"toolName":"ed"}',
    );
    expect(card('ed').querySelector(`label[for="${sw.id}"]`)).toBeNull();
    expect(container.textContent).not.toContain('settings.tools.inMyChats');
  });

  // The tool can't be in the caller's chats at all (the composer picker
  // hides it too), so there is no state to show: no switch, no bare grey one.
  it('hides the switch for a shared tool without use_in_own', async () => {
    await render([viewerTool]);
    expect(card('vw').querySelector('[role="switch"]')).toBeNull();
  });

  it('reverts the switch and shows an error toast when the update fails', async () => {
    await render([editorTool]);
    updateToolStatus.mockImplementation(() =>
      jsonResponse({ success: false, message: 'Forbidden' }, false, 403),
    );
    await act(async () => switchOf('ed').click());
    expect(updateToolStatus).toHaveBeenCalledWith(
      { id: 'ed', status: true },
      'token',
    );
    expect(switchOf('ed').getAttribute('aria-checked')).toBe('false');
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: expect.objectContaining({ variant: 'destructive' }),
      }),
    );
  });

  it('keeps the new value when the update succeeds', async () => {
    await render([editorTool]);
    // Mounting loads the connectors; only a toast would come after it.
    dispatch.mockClear();
    updateToolStatus.mockImplementation(() => jsonResponse({ success: true }));
    await act(async () => switchOf('ed').click());
    expect(switchOf('ed').getAttribute('aria-checked')).toBe('true');
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('shows the role on a shared tile as a neutral Users Badge', async () => {
    await render([ownTool, editorTool, viewerTool]);
    const badge = (id: string) =>
      card(id).querySelector<HTMLElement>('[data-testid="role-badge"]');
    expect(badge('own')).toBeNull();
    expect(badge('ed')?.dataset.variant).toBe('neutral');
    expect(badge('ed')?.textContent).toBe('teamAccess.editor');
    expect(badge('vw')?.textContent).toBe('teamAccess.viewer');
    expect(
      badge('ed')?.querySelector('svg')?.getAttribute('class'),
    ).not.toContain('size-3');
  });

  // "Configured" is not a health check: only a real state gets a badge.
  it('badges a custom MCP server only when it is connected or needs reconnecting', async () => {
    mcpStatuses.value = {
      own: 'configured',
      ed: 'needs_auth',
      vw: 'connected',
    };
    await render([ownTool, editorTool, viewerTool]);
    const state = (id: string) =>
      card(id).querySelector<HTMLElement>('[data-slot="badge"]');
    expect(state('own')).toBeNull();
    expect(state('ed')?.textContent).toBe(
      'settings.connectors.status.reconnect',
    );
    expect(state('ed')?.dataset.variant).toBe('warning');
    expect(state('vw')?.textContent).toBe(
      'settings.connectors.status.connected',
    );
    expect(state('vw')?.dataset.variant).toBe('success');
  });

  it('keeps names as typed and drops the fixed tile height', async () => {
    await render([{ ...ownTool, displayName: 'ntfy' }]);
    const tile = card('ntfy');
    expect(tile.className).not.toMatch(/\bh-52\b/);
    expect(
      tile.querySelector('[data-slot="card-title"]')!.className,
    ).not.toContain('capitalize');
    expect(
      tile
        .querySelector('[data-slot="card-description"]')!
        .hasAttribute('title'),
    ).toBe(false);
  });

  it('says there are no tools yet and offers both ways to add one', async () => {
    await render([]);
    const empty = container.querySelector('[data-slot="empty-state"]')!;
    expect(empty.textContent).toContain('settings.tools.noToolsYet');
    const actions = Array.from(
      empty.querySelectorAll<HTMLButtonElement>('button'),
    );
    expect(actions.map((b) => b.textContent)).toEqual([
      'settings.tools.addTool',
      'settings.tools.connectService',
    ]);
    await act(async () => actions[1].click());
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      '/settings/connectors?capability=tools',
    );
  });

  it('shows a small no-match line for a search with no results', async () => {
    await render([ownTool]);
    const input =
      container.querySelector<HTMLInputElement>('#tool-search-input')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )!.set!.call(input, 'zzz');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const empty = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"]',
    )!;
    expect(empty.dataset.size).toBe('xs');
    expect(empty.querySelector('img')).toBeNull();
    expect(empty.textContent).toContain('settings.tools.noToolsFound');
  });
});

describe('Tools page connections', () => {
  let container: HTMLDivElement;
  let root: Root;

  const TOOLS = [
    {
      id: 'tg',
      name: 'telegram',
      displayName: 'Telegram · Alerts bot',
      customName: 'Telegram · Alerts bot',
      description: 'Send messages',
      status: true,
      config: {},
      actions: [],
      connection_id: 'conn-1',
    },
    {
      id: 'api',
      name: 'api_tool',
      displayName: 'API Tool',
      customName: 'My API',
      description: 'Calls an API',
      status: true,
      config: {},
      actions: [],
      connection_id: null,
    },
    {
      id: 'lin',
      name: 'mcp_tool',
      displayName: 'Linear',
      customName: '',
      description: 'MCP Server: https://mcp.linear.app/mcp',
      status: true,
      config: {},
      actions: [],
      connection_id: 'conn-2',
    },
  ];

  beforeEach(() => {
    reduxState.connectors.catalog = [
      {
        key: 'telegram',
        name: 'Telegram',
        description: 'Send messages to a chat.',
        publisher: 'built_in',
        available: true,
        capabilities: ['write'],
      },
      {
        key: 'mcp:linear',
        name: 'Linear',
        description: 'Issues and projects.',
        publisher: 'preset',
        available: true,
        capabilities: ['write'],
      },
    ];
    reduxState.connectors.connections = [
      {
        id: 'conn-1',
        connector_key: 'telegram',
        name: 'Telegram',
        icon: 'tool_telegram',
        status: 'connected',
        account_label: '…abcd',
        account_name: 'Alerts bot',
      },
      {
        id: 'conn-2',
        connector_key: 'mcp:linear',
        name: 'Linear',
        icon: 'linear',
        status: 'reconnect_needed',
        account_label: 'Linear',
      },
    ];
    dispatch.mockReset();
    getUserTools.mockReset();
    getUserTools.mockImplementation(() => jsonResponse({ tools: TOOLS }));
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const card = (title: string) =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="card-title"]'),
    )
      .find((h) => h.textContent === title)!
      .closest<HTMLElement>('[data-slot="card"]')!;
  const menuItem = (title: string, label: string) =>
    Array.from(
      card(title).querySelectorAll<HTMLButtonElement>(
        '[data-testid="menu"] button',
      ),
    ).find((b) => b.textContent === label);

  // A connected tool is managed on the Connectors page; its card keeps
  // what acts on the tool itself.
  it('gives the owner of a connected tool Manage in Connectors first, then Share and Delete', async () => {
    await renderTools(root);
    expect(
      Array.from(
        card('Telegram').querySelectorAll('[data-testid="menu"] button'),
      ).map((b) => b.textContent),
    ).toEqual([
      'settings.tools.manageInConnectors',
      'settings.tools.shareWithTeam',
      'settings.tools.delete',
    ]);
    await act(async () =>
      menuItem('Telegram', 'settings.tools.manageInConnectors')!.click(),
    );
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      '/settings/connectors?connector=telegram&connection=conn-1',
    );
  });

  it("offers no Manage in Connectors on a teammate's connected tool", async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[0],
            customName: 'Telegram (shared)',
            connection_id: 'owner-conn',
            access: 'editor',
            ownership: 'team',
            allowed_actions: ['edit', 'use', 'use_in_own'],
          },
        ],
      }),
    );
    await renderTools(root);
    expect(
      menuItem('Telegram (shared)', 'settings.tools.manageInConnectors'),
    ).toBeUndefined();
  });

  it('groups the tools like the composer: built in, each service, custom', async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          ...TOOLS,
          {
            id: 'mem',
            name: 'memory',
            displayName: 'Memory',
            customName: '',
            description: 'Remembers',
            status: true,
            config: {},
            actions: [],
            default: true,
          },
        ],
      }),
    );
    await renderTools(root);
    const headers = Array.from(
      container.querySelectorAll('[data-slot="section-header"] h2'),
    ).map((h) => h.textContent);
    expect(headers).toEqual([
      'settings.tools.groupBuiltIn',
      'Telegram',
      'Linear',
      'agents.form.toolsPopup.groupCustom',
    ]);
    const section = (title: string) =>
      Array.from(container.querySelectorAll('section')).find(
        (s) => s.querySelector('h2')?.textContent === title,
      )!;
    expect(section('Telegram').textContent).toContain('Alerts bot');
    expect(section('agents.form.toolsPopup.groupCustom').textContent).toContain(
      'My API',
    );
    // The default copy is told apart by a neutral Default badge; the old
    // "Built-in" badge is gone (the group says it).
    const memory = section('settings.tools.groupBuiltIn');
    const badge = memory.querySelector<HTMLElement>('[data-slot="badge"]')!;
    expect(badge.textContent).toBe('settings.tools.defaultBadge');
    expect(badge.dataset.variant).toBe('neutral');
    expect(container.textContent).not.toContain('settings.tools.builtIn');
  });

  it("draws a connected tool with its service's logo and no icon in the footer", async () => {
    await renderTools(root);
    const header = card('Linear').querySelector('[data-slot="card-header"]')!;
    // The service logo is decorative (the name is beside it); the generic
    // MCP tool icon would carry an accessible name.
    expect(header.querySelector('svg')).not.toBeNull();
    expect(header.querySelector('[role="img"]')).toBeNull();
    expect(
      card('My API').querySelector('[data-slot="card-header"] [role="img"]'),
    ).not.toBeNull();
    expect(
      card('Telegram').querySelector('[data-slot="card-footer"] svg'),
    ).toBeNull();
  });

  it('shows each connected account as its own tool, the account on its footer', async () => {
    await renderTools(root);
    const telegram = card('Telegram');
    // Which account this card is beside its own switch, and the catalog's
    // plain description.
    const footer = telegram.querySelector('[data-slot="card-footer"]')!;
    expect(footer.textContent).toBe('Alerts bot');
    expect(footer.querySelector('[role="switch"]')).not.toBeNull();
    expect(telegram.textContent).toContain(
      'settings.connectors.descriptions.telegram',
    );
  });

  it('names an account by its login, not as a key ending', async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          ...TOOLS,
          {
            id: 'gh',
            name: 'mcp_tool',
            displayName: 'GitHub',
            customName: '',
            description: '',
            status: true,
            config: {},
            actions: [],
            connection_id: 'conn-gh',
          },
        ],
      }),
    );
    reduxState.connectors.connections = [
      ...reduxState.connectors.connections,
      {
        id: 'conn-gh',
        connector_key: 'github',
        name: 'GitHub',
        icon: 'github',
        status: 'connected',
        auth_kind: 'api_key',
        account_label: 'dartpain',
      },
    ];
    await renderTools(root);
    const footer = card('GitHub').querySelector('[data-slot="card-footer"]')!;
    expect(footer.textContent).toBe('dartpain');
  });

  it('says a connected tool needs reconnecting, with no raw MCP reconnect', async () => {
    await renderTools(root);
    const badge = card('Linear').querySelector<HTMLElement>(
      '[data-slot="badge"]',
    )!;
    expect(badge.textContent).toBe('settings.connectors.status.reconnect');
    expect(badge.dataset.variant).toBe('warning');
    expect(card('Linear').textContent).not.toContain(
      'settings.connectors.health.signInAgain',
    );
    expect(card('Linear').textContent).not.toContain('MCP Server:');
    expect(menuItem('Linear', 'settings.tools.reconnect')).toBeUndefined();
  });

  // The owner signs in again right from the card; an MCP preset re-signs
  // its existing tool.
  it('offers the owner Reconnect on a connected tool that needs it', async () => {
    reconnect.mockClear();
    await renderTools(root);
    expect(
      menuItem('Telegram', 'settings.connectors.status.reconnect'),
    ).toBeUndefined();
    await act(async () =>
      menuItem('Linear', 'settings.connectors.status.reconnect')!.click(),
    );
    expect(reconnect).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'conn-2', connector_key: 'mcp:linear' }),
      'lin',
    );
  });

  it("offers no Sign in again on a teammate's connected tool", async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[2],
            customName: 'Linear (shared)',
            connection_id: 'owner-conn',
            access: 'editor',
            ownership: 'team',
            allowed_actions: ['edit', 'use', 'use_in_own'],
          },
        ],
      }),
    );
    await renderTools(root);
    expect(
      menuItem('Linear (shared)', 'settings.connectors.status.reconnect'),
    ).toBeUndefined();
  });

  it('keeps Edit for a tool that is not from a connection', async () => {
    await renderTools(root);
    expect(menuItem('My API', 'settings.tools.edit')).toBeDefined();
    expect(card('My API').querySelector('[role="switch"]')).not.toBeNull();
  });

  it("gives a viewer of a teammate's connected tool View", async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[0],
            customName: 'Telegram (shared)',
            connection_id: 'owner-conn',
            access: 'viewer',
            ownership: 'team',
            team_access: 'viewer',
            allowed_actions: ['use', 'use_in_own'],
          },
        ],
      }),
    );
    await renderTools(root);
    expect(menuItem('Telegram (shared)', 'settings.tools.view')).toBeDefined();
    expect(
      menuItem('Telegram (shared)', 'settings.tools.reconnect'),
    ).toBeUndefined();
  });

  // The connections load after the tools; the owner must not see the raw
  // MCP Reconnect for a connected tool in between.
  it("offers no Reconnect for the owner's connected MCP tool before connections load", async () => {
    reduxState.connectors.connections = [];
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[2],
            customName: 'Linear (mine)',
            config: { auth_type: 'bearer' },
            access: 'owner',
          },
        ],
      }),
    );
    await renderTools(root);
    expect(
      menuItem('Linear (mine)', 'settings.tools.reconnect'),
    ).toBeUndefined();
    // Nor the tool editor: the owner manages it on the Connectors page.
    expect(menuItem('Linear (mine)', 'settings.tools.edit')).toBeUndefined();
  });

  it("shows an editor who may share the owner's account, locked, with the write confirmation", async () => {
    shareModalProps.mockReset();
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[0],
            customName: 'Telegram (shared)',
            connection_id: 'owner-conn',
            credential_mode: 'owner',
            actions: [{ name: 'send', access: 'write' }],
            access: 'editor',
            ownership: 'team',
            team_access: 'editor',
            allowed_actions: ['edit', 'share', 'use', 'use_in_own'],
          },
        ],
      }),
    );
    await renderTools(root);
    await act(async () =>
      menuItem('Telegram (shared)', 'settings.tools.shareWithTeam')!.click(),
    );
    const props = shareModalProps.mock.calls.at(-1)?.[0] as {
      credentials?: Record<string, unknown>;
    };
    expect(props.credentials).toMatchObject({
      toolId: 'tg',
      connectorName: 'Telegram',
      mode: 'owner',
      hasWrites: true,
      readOnly: true,
    });
  });

  it("offers no Reconnect for a teammate's connected MCP tool", async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({
        tools: [
          {
            ...TOOLS[2],
            customName: 'Linear (shared)',
            connection_id: 'owner-conn',
            config: { auth_type: 'bearer' },
            access: 'editor',
            ownership: 'team',
            allowed_actions: ['edit', 'edit_credentials', 'use', 'use_in_own'],
          },
        ],
      }),
    );
    await renderTools(root);
    expect(
      menuItem('Linear (shared)', 'settings.tools.reconnect'),
    ).toBeUndefined();
    expect(menuItem('Linear (shared)', 'settings.tools.edit')).toBeDefined();
  });

  it('shows a failed load as an error with Retry, not "no tools yet"', async () => {
    getUserTools.mockImplementation(() =>
      jsonResponse({ success: false }, false, 500),
    );
    await renderTools(root);
    const state = container.querySelector<HTMLElement>(
      '[data-slot="empty-state"][data-tone="destructive"]',
    )!;
    expect(state).not.toBeNull();
    expect(state.textContent).toContain('settings.tools.loadError');
    expect(container.textContent).not.toContain('settings.tools.noToolsYet');
    getUserTools.mockImplementation(() => jsonResponse({ tools: [ownTool] }));
    const retry = Array.from(state.querySelectorAll('button')).find(
      (b) => b.textContent === 'retry',
    )!;
    await act(async () => retry.click());
    expect(
      container.querySelector(
        '[data-slot="empty-state"][data-tone="destructive"]',
      ),
    ).toBeNull();
    expect(card('own')).toBeDefined();
  });
});
