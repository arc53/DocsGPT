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
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
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
vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: (...args: unknown[]) => getUserTools(...args),
    getMCPAuthStatus: () =>
      Promise.resolve({ json: () => Promise.resolve({ success: false }) }),
    updateToolStatus: (...args: unknown[]) => updateToolStatus(...args),
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
      .find((c) => c.querySelector('h2')?.textContent === name)!;
  const menuLabels = (id: string) =>
    Array.from(card(id).querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );
  const switchOf = (id: string) =>
    card(id).querySelector<HTMLButtonElement>('[role="switch"]')!;

  it('shows Edit, Reconnect, Share and Delete to the owner', async () => {
    await render([ownTool]);
    expect(menuLabels('own')).toEqual([
      'settings.tools.edit',
      'settings.tools.reconnect',
      'settings.tools.shareWithTeam',
      'settings.tools.delete',
    ]);
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
    Array.from(container.querySelectorAll<HTMLElement>('h2'))
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
  it('gives the owner of a connected tool Share and Delete, no connection item', async () => {
    await renderTools(root);
    expect(
      Array.from(
        card('Telegram').querySelectorAll('[data-testid="menu"] button'),
      ).map((b) => b.textContent),
    ).toEqual(['settings.tools.shareWithTeam', 'settings.tools.delete']);
    expect(
      menuItem('Telegram', 'settings.connectors.manageConnection'),
    ).toBeUndefined();
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

  it('says a connected tool needs signing in again, with no raw MCP reconnect', async () => {
    await renderTools(root);
    expect(card('Linear').textContent).toContain(
      'settings.connectors.health.signInAgain',
    );
    expect(card('Linear').textContent).not.toContain('MCP Server:');
    expect(menuItem('Linear', 'settings.tools.reconnect')).toBeUndefined();
  });

  // The owner signs in again right from the card; an MCP preset re-signs
  // its existing tool.
  it('offers the owner Sign in again on a connected tool that needs it', async () => {
    reconnect.mockClear();
    await renderTools(root);
    expect(
      menuItem('Telegram', 'settings.connectors.health.signInAgain'),
    ).toBeUndefined();
    await act(async () =>
      menuItem('Linear', 'settings.connectors.health.signInAgain')!.click(),
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
      menuItem('Linear (shared)', 'settings.connectors.health.signInAgain'),
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
});
