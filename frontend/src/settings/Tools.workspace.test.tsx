import { act, useState, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import type { Folder } from '../components/folders/types';
import { PERSONAL_ROW, type WorkspaceRole } from '../workspace/workspaceSlice';

// The store's slices the page reads; each test sets the workspace.
const reduxState = vi.hoisted(() => ({
  preference: { token: 'token' },
  connectors: {
    enabled: true,
    catalog: [] as unknown[],
    connections: [] as unknown[],
    loaded: true,
    loading: false,
    failed: false,
  },
  notifications: { recentEvents: [] as unknown[] },
  folders: {
    tree: {
      items: [] as unknown[],
      loaded: true,
      loading: false,
      failed: false,
      latestRequestId: null,
      removedParents: {},
    },
  },
  workspace: {} as Record<string, unknown>,
}));
const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  // A fresh root object per read: memoized selectors cache by it, and the
  // tests change the workspace in place.
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ ...reduxState }),
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
  useMediaQuery: () => ({ isMobile: false, isDesktop: true }),
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

// A Radix select renders its items only while open; here they are always
// in the page, so the MCP form's auth types can be read.
vi.mock('../components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <div data-testid="select-item" data-value={value}>
      {children}
    </div>
  ),
}));

vi.mock('./ToolConfig', () => ({ default: () => null }));
vi.mock('./RemoteDeviceConfig', () => ({ default: () => null }));
const addTool = vi.hoisted(() => ({
  props: null as null | { onToolsCreated: (ids: string[]) => void },
}));
vi.mock('../modals/AddToolModal', () => ({
  default: (props: { onToolsCreated: (ids: string[]) => void }) => {
    addTool.props = props;
    return null;
  },
}));
vi.mock('../modals/ConfirmationModal', () => ({ default: () => null }));
// The Share dialog's props, from its last render.
const share = vi.hoisted(() => ({
  props: null as null | { onMoved?: () => void },
}));
vi.mock('../teams/ShareToTeamModal', () => ({
  default: (props: { onMoved?: () => void }) => {
    share.props = props;
    return null;
  },
}));
vi.mock('../api/services/devicesService', () => ({ default: {} }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));

// The Move to team option, as the page's hook gives it.
const moveToWorkspace = vi.hoisted(() => ({ kinds: [] as string[] }));
vi.mock('../workspace/move/useMoveToWorkspace', () => {
  const hook = (kind: string) => {
    moveToWorkspace.kinds.push(kind);
    return {
      menuOption: () => ({
        label: 'workspace.menu.moveToTeam',
        onClick: () => {},
      }),
      dialog: null,
    };
  };
  return { useMoveToWorkspace: hook, default: hook };
});

const api = vi.hoisted(() => ({
  getUserTools: vi.fn(),
  getMCPAuthStatus: vi.fn(),
  fileFolderItems: vi.fn(),
  testMCPConnection: vi.fn(),
  saveMCPServer: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({ default: api }));

import Tools from './Tools';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const jsonResponse = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const baseTool = {
  name: 'api_tool',
  description: 'Rates',
  config: {},
  actions: [],
  status: true,
};
const personal = { kind: 'personal', team_id: null };
const ownTool = {
  ...baseTool,
  id: 'own',
  displayName: 'Rate lookup',
  in_chat: true,
  access: 'owner',
  origin: 'own',
  workspace: personal,
  created_by: { user_id: 'me', label: 'Lena' },
  allowed_actions: ['delete', 'edit', 'share', 'use', 'move_folder'],
  folder_id: null,
};
const filedTool = {
  ...ownTool,
  id: 'filed',
  displayName: 'Customs codes',
  folder_id: 'f-customs',
};
const sharedTool = {
  ...baseTool,
  id: 'shared',
  displayName: 'Port feed',
  in_chat: false,
  access: 'viewer',
  ownership: 'team',
  team_access: 'viewer',
  origin: 'shared',
  workspace: personal,
  created_by: { user_id: 'priya', label: 'Priya' },
  allowed_actions: ['use'],
};
const teamTool = {
  ...baseTool,
  id: 'team',
  displayName: 'Lane pricing',
  // A team tool's own status is always off; "in my chats" is per person.
  status: false,
  in_chat: false,
  access: 'editor',
  origin: 'team',
  workspace: { kind: 'team', team_id: 't1' },
  created_by: { user_id: 'dana', label: 'Dana' },
  allowed_actions: ['edit', 'use', 'use_in_own', 'move_folder'],
};

const folders: Folder[] = [
  {
    id: 'f-customs',
    name: 'Customs & compliance',
    parent_id: null,
    counts: { tool: 1, prompt: 3 },
  },
  {
    // Holds only prompts: it stays on the Prompts page.
    id: 'f-prompts',
    name: 'Customer replies',
    parent_id: null,
    counts: { prompt: 4 },
  },
];

const setWorkspace = (role?: WorkspaceRole) => {
  reduxState.workspace = {
    current: role ? 't1' : 'personal',
    workspaces: role
      ? [
          PERSONAL_ROW,
          {
            id: 't1',
            kind: 'team',
            name: 'Operations',
            role,
            member_count: 12,
          },
        ]
      : [PERSONAL_ROW],
    loaded: true,
    loading: false,
    epoch: 0,
    lastReason: null,
    latestRequestId: null,
  };
};

describe('Tools page in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    api.getMCPAuthStatus.mockImplementation(() =>
      jsonResponse({ success: true, statuses: {} }),
    );
    api.fileFolderItems.mockImplementation(() =>
      jsonResponse({ moved: ['t9'], skipped: [] }),
    );
    reduxState.folders.tree.items = folders;
    moveToWorkspace.kinds = [];
    dispatch.mockReset();
    setWorkspace();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (tools: unknown[], entry = '/settings/tools') => {
    api.getUserTools.mockImplementation(() => jsonResponse({ tools }));
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={[entry]}>
          <Routes>
            <Route path="/settings/tools" element={<Tools />} />
          </Routes>
        </MemoryRouter>,
      );
    });
  };

  const headings = () =>
    Array.from(container.querySelectorAll('h2')).map((h) => h.textContent);
  const section = (title: string) =>
    Array.from(container.querySelectorAll('section')).find((s) =>
      s.querySelector('h2')?.textContent?.startsWith(title),
    );
  const tileTitles = (root: ParentNode = container) =>
    Array.from(root.querySelectorAll('h3')).map((h) => h.textContent);
  const tile = (name: string) =>
    Array.from(
      container.querySelectorAll<HTMLElement>('[data-slot="card"]'),
    ).find((c) => c.querySelector('h3')?.textContent === name)!;
  const folderTiles = () =>
    Array.from(container.querySelectorAll('[data-folder-tile]')).map((t) =>
      t.getAttribute('data-folder-tile'),
    );
  const button = (text: string) =>
    Array.from(container.querySelectorAll<HTMLButtonElement>('button')).find(
      (b) => b.textContent === text,
    );

  it('in Personal: the line, folders, your tools, then Shared with you', async () => {
    await render([ownTool, filedTool, sharedTool]);
    expect(
      container.querySelector('[data-testid="workspace-line"]'),
    ).not.toBeNull();
    expect(headings()[0]).toBe('settings.tools.sections.folders1');
    expect(headings()[headings().length - 1]).toBe(
      'workspace.page.sharedWithYou1',
    );
    // A folder with only prompts stays off the Tools page.
    expect(folderTiles()).toEqual(['f-customs']);
    // A filed tool is in its folder, not at the root.
    expect(tileTitles()).not.toContain('Customs codes');
    expect(tileTitles(section('workspace.page.sharedWithYou')!)).toEqual([
      'Port feed',
    ]);
    const shared = tile('Port feed');
    expect(
      shared.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Priya');
    expect(shared.querySelector('[data-testid="role-meta"]')).not.toBeNull();
    const own = tile('Rate lookup');
    expect(own.querySelector('[data-testid="role-meta"]')).toBeNull();
    expect(own.querySelector('[data-testid="creator-meta"]')).toBeNull();
  });

  it('in a team: tiles name who added them, no role, no Shared with you', async () => {
    setWorkspace('editor');
    await render([teamTool]);
    expect(headings()).not.toContainEqual(
      expect.stringMatching(/^workspace\.page\.sharedWithYou/),
    );
    const team = tile('Lane pricing');
    expect(
      team.querySelector('[data-testid="creator-meta"]')?.textContent,
    ).toBe('Dana');
    expect(team.querySelector('[data-testid="role-meta"]')).toBeNull();
    // Each member's own "in my chats" switch, off by default.
    expect(
      team.querySelector('[role="switch"]')?.getAttribute('aria-checked'),
    ).toBe('false');
    expect(button('settings.tools.addTool')).toBeDefined();
    expect(button('folders.newFolder')).toBeDefined();
    // Connected services are personal: no "Connect a service" in a team.
    expect(button('settings.tools.connectService')).toBeUndefined();
  });

  it('in a team, a Viewer gets no Add tool and no New folder', async () => {
    setWorkspace('viewer');
    await render([teamTool]);
    expect(button('settings.tools.addTool')).toBeUndefined();
    expect(button('folders.newFolder')).toBeUndefined();
  });

  it('inside a folder lists only the tools filed there', async () => {
    await render(
      [ownTool, filedTool, sharedTool],
      '/settings/tools?folder=f-customs',
    );
    expect(tileTitles()).toEqual(['Customs codes']);
    expect(
      container.querySelector('[data-slot="folder-crumb-row"]')?.textContent,
    ).toContain('Customs & compliance');
  });

  it('a tool added inside a folder is filed in it', async () => {
    await render([ownTool, filedTool], '/settings/tools?folder=f-customs');
    await act(async () => {
      addTool.props!.onToolsCreated(['t9']);
    });
    expect(api.fileFolderItems).toHaveBeenCalledWith(
      { type: 'tool', folder_id: 'f-customs', ids: ['t9'] },
      'token',
    );
  });

  it('a tool added at the root is filed nowhere', async () => {
    await render([ownTool]);
    await act(async () => {
      addTool.props!.onToolsCreated(['t9']);
    });
    expect(api.fileFolderItems).not.toHaveBeenCalled();
  });

  it('offers Move to folder and Move to team on a tool of yours', async () => {
    await render([ownTool, sharedTool]);
    const labels = (name: string) =>
      Array.from(
        tile(name).querySelectorAll('[data-testid="menu"] button'),
      ).map((b) => b.textContent);
    expect(labels('Rate lookup')).toContain('folders.moveToFolder');
    expect(labels('Rate lookup')).toContain('workspace.menu.moveToTeam');
    expect(moveToWorkspace.kinds).toContain('tool');
  });

  const menuLabels = (name: string) =>
    Array.from(tile(name).querySelectorAll('[data-testid="menu"] button')).map(
      (b) => b.textContent,
    );

  it("offers Share on a team's tool to a Viewer, to see who has access", async () => {
    setWorkspace('viewer');
    await render([
      { ...teamTool, access: 'viewer', allowed_actions: ['use', 'use_in_own'] },
    ]);
    expect(menuLabels('Lane pricing')).toContain(
      'settings.tools.shareWithTeam',
    );
  });

  it("reloads the list when the Share dialog's offer moves the tool", async () => {
    // Not a plain assignment, which would narrow `props` to null below.
    Object.assign(share, { props: null });
    await render([ownTool]);
    const shareItem = Array.from(
      tile('Rate lookup').querySelectorAll<HTMLButtonElement>(
        '[data-testid="menu"] button',
      ),
    ).find((b) => b.textContent === 'settings.tools.shareWithTeam')!;
    await act(async () => shareItem.click());
    expect(share.props?.onMoved).toBeTypeOf('function');
    const loads = api.getUserTools.mock.calls.length;
    await act(async () => share.props!.onMoved!());
    expect(api.getUserTools.mock.calls.length).toBeGreaterThan(loads);
  });
});

describe('MCP server form in a workspace', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (server?: Record<string, unknown>) => {
    const { default: MCPServerModal } = await vi.importActual<
      typeof import('../modals/MCPServerModal')
    >('../modals/MCPServerModal');
    await act(async () => {
      root.render(
        <MCPServerModal
          modalState="ACTIVE"
          setModalState={() => {}}
          server={server}
          onServerSaved={() => {}}
        />,
      );
    });
  };
  const authTypes = () =>
    Array.from(
      document.body.querySelectorAll('[data-testid="select-item"]'),
    ).map((item) => item.getAttribute('data-value'));

  it('offers OAuth sign-in in Personal', async () => {
    setWorkspace();
    await render();
    expect(authTypes()).toContain('oauth');
  });

  it("hides OAuth sign-in in a team, which can't hold a sign-in", async () => {
    setWorkspace('editor');
    await render();
    expect(authTypes()).toEqual(['none', 'api_key', 'bearer']);
    expect(document.body.textContent).toContain(
      'settings.tools.mcp.oauthPersonalOnly',
    );
  });
});
