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
vi.mock('../teams/ShareToTeamModal', () => ({ default: () => null }));
vi.mock('../api/services/devicesService', () => ({ default: {} }));

// The connector panel itself is tested on its own; here it only has to open
// for the right service.
vi.mock('../connectors/ConnectionDrawer', () => ({
  default: ({
    connector,
    initialConnectionId,
  }: {
    connector: { key: string } | null;
    initialConnectionId?: string;
  }) =>
    connector ? (
      <div data-testid="drawer">{`${connector.key}:${initialConnectionId}`}</div>
    ) : null,
}));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch: vi.fn(), modals: null }),
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

  it('labels the switch "In my chats" and binds it to in_chat', async () => {
    await render([ownTool, editorTool]);
    const sw = switchOf('ed');
    expect(sw.getAttribute('aria-checked')).toBe('false');
    expect(switchOf('own').getAttribute('aria-checked')).toBe('true');
    const label = card('ed').querySelector<HTMLLabelElement>(
      `label[for="${sw.id}"]`,
    );
    expect(label?.textContent).toBe('settings.tools.inMyChats');
    expect(sw.getAttribute('aria-label')).toBe(
      'settings.tools.useInMyChatsAria:{"toolName":"ed"}',
    );
  });

  // The tool can't be in the caller's chats at all (the composer picker
  // hides it too), so there is no state to show: no switch, no bare grey one.
  it('hides the switch and its label for a shared tool without use_in_own', async () => {
    await render([viewerTool]);
    expect(card('vw').querySelector('[role="switch"]')).toBeNull();
    expect(card('vw').textContent).not.toContain('settings.tools.inMyChats');
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

  it('opens the connection panel right here to manage a connected tool', async () => {
    await renderTools(root);
    expect(menuItem('Telegram', 'settings.tools.edit')).toBeUndefined();
    await act(async () =>
      menuItem('Telegram', 'settings.connectors.manageConnection')!.click(),
    );
    expect(
      document.body.querySelector('[data-testid="drawer"]')?.textContent,
    ).toBe('telegram:conn-1');
    // Stays on the Tools page.
    expect(document.body.querySelector('[data-testid="where"]')).toBeNull();
  });

  it('shows each connected account as its own tool with its own switch', async () => {
    await renderTools(root);
    const telegram = card('Telegram');
    expect(telegram.querySelector('[role="switch"]')).not.toBeNull();
    // Which account this card is, and the catalog's plain description.
    expect(telegram.textContent).toContain('Alerts bot');
    expect(telegram.textContent).toContain(
      'settings.connectors.descriptions.telegram',
    );
    // Managing the connection lives in the menu, not on the card.
    expect(
      Array.from(telegram.querySelectorAll('button')).some(
        (b) =>
          !b.closest('[data-testid="menu"]') &&
          b.textContent === 'settings.connectors.manageConnection',
      ),
    ).toBe(false);
  });

  it('says a connected tool needs signing in again, with no raw MCP reconnect', async () => {
    await renderTools(root);
    expect(card('Linear').textContent).toContain(
      'settings.connectors.health.signInAgain',
    );
    expect(card('Linear').textContent).not.toContain('MCP Server:');
    expect(menuItem('Linear', 'settings.tools.reconnect')).toBeUndefined();
  });

  it('keeps Edit for a tool that is not from a connection', async () => {
    await renderTools(root);
    expect(menuItem('My API', 'settings.tools.edit')).toBeDefined();
    expect(
      menuItem('My API', 'settings.connectors.manageConnection'),
    ).toBeUndefined();
    expect(card('My API').querySelector('[role="switch"]')).not.toBeNull();
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
