import { act, type ReactNode } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

import { PERSONAL_ROW, type WorkspaceRole } from '../workspace/workspaceSlice';

// The store's slices the form reads; each test sets the team role.
const state = vi.hoisted(() => ({
  events: [] as unknown[],
  workspace: {} as Record<string, unknown>,
}));
const dispatch = vi.hoisted(() => vi.fn());
vi.mock('react-redux', () => ({
  useSelector: (selector: (s: unknown) => unknown) =>
    selector({
      notifications: { recentEvents: state.events },
      preference: {},
      workspace: state.workspace,
    }),
  useDispatch: () => dispatch,
}));
vi.mock('../preferences/preferenceSlice', () => ({
  selectToken: () => 'token',
}));
vi.mock('../notifications/notificationsSlice', () => ({
  selectRecentEvents: (s: { notifications: { recentEvents: unknown[] } }) =>
    s.notifications.recentEvents,
}));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
// A Radix select renders its items only while open; here they are always
// in the page, so the auth types on offer can be read.
vi.mock('../components/ui/select', () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  SelectItem: ({ value }: { value: string }) => (
    <div data-testid="select-item" data-value={value} />
  ),
}));

const api = vi.hoisted(() => ({
  testMCPConnection: vi.fn(),
  saveMCPServer: vi.fn(),
  createMemberTool: vi.fn(),
}));
vi.mock('../api/services/userService', () => ({
  default: {
    testMCPConnection: (...a: unknown[]) => api.testMCPConnection(...a),
    saveMCPServer: (...a: unknown[]) => api.saveMCPServer(...a),
  },
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    createMemberTool: (...a: unknown[]) => api.createMemberTool(...a),
  },
}));

import MCPServerModal from './MCPServerModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

const setRole = (role: WorkspaceRole) => {
  state.workspace = {
    current: 't1',
    workspaces: [
      PERSONAL_ROW,
      { id: 't1', kind: 'team', name: 'Ops', role, member_count: 3 },
    ],
    loaded: true,
  };
};

// A new server that signs in, as the Add tool form or a preset opens it.
const newServer = {
  displayName: 'Tracker',
  server_url: 'https://mcp.tracker.dev/mcp',
  auth_type: 'oauth',
  oauth_scopes: '',
};

const seen = vi.hoisted(() => ({
  location: null as null | { pathname: string; state: unknown },
}));
function LocationProbe() {
  const location = useLocation();
  seen.location = { pathname: location.pathname, state: location.state };
  return null;
}

describe('MCP server form in a team', () => {
  let container: HTMLDivElement;
  let root: Root;
  let onServerSaved: ReturnType<
    typeof vi.fn<(id?: string, saved?: unknown) => void>
  >;
  let props: Record<string, unknown>;

  beforeEach(() => {
    Object.values(api).forEach((fn) => fn.mockReset());
    dispatch.mockReset();
    state.events = [];
    seen.location = null;
    onServerSaved = vi.fn();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (server: Record<string, unknown> = newServer) => {
    props = { server };
    await act(async () => {
      root.render(
        <MemoryRouter initialEntries={['/settings/tools']}>
          <Routes>
            <Route
              path="*"
              element={
                <>
                  <LocationProbe />
                  <MCPServerModal
                    modalState="ACTIVE"
                    setModalState={() => {}}
                    server={props.server}
                    onServerSaved={onServerSaved}
                  />
                </>
              }
            />
          </Routes>
        </MemoryRouter>,
      );
    });
  };
  // Re-render on the same server, as a new event in the store would.
  const rerender = () => render(props.server as Record<string, unknown>);

  const text = () => document.body.textContent ?? '';
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === label);
  const radio = (value: string) =>
    document.body.querySelector<HTMLButtonElement>(
      `[role="radio"][value="${value}"]`,
    );

  it('adds a sign-in server for each person when an Editor saves it, with no test and no team sign-in', async () => {
    setRole('editor');
    api.createMemberTool.mockResolvedValue({ success: true, id: 'tool-m' });
    await render();
    // Only an Admin signs in for the team: no choice is drawn.
    expect(radio('team')).toBeNull();
    expect(text()).not.toContain('settings.tools.mcp.team.teamOnce');
    expect(text()).toContain('settings.tools.mcp.team.eachPersonHint');
    expect(button('settings.tools.mcp.testConnection')).toBeUndefined();
    const save = button('settings.tools.mcp.save')!;
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(api.createMemberTool).toHaveBeenCalledWith(
      {
        connector_key: 'custom_mcp',
        server_url: 'https://mcp.tracker.dev/mcp',
        displayName: 'Tracker',
      },
      'token',
    );
    expect(api.saveMCPServer).not.toHaveBeenCalled();
    expect(onServerSaved).toHaveBeenCalledWith('tool-m', {
      connectionId: null,
    });
  });

  it('lets an Admin sign in once for the team, testing and saving with owner team', async () => {
    setRole('admin');
    api.testMCPConnection.mockReturnValue(
      json({ success: false, requires_oauth: true, task_id: 'task-1' }),
    );
    api.saveMCPServer.mockReturnValue(
      json({ success: true, id: 'tool-t', connection_id: 'conn-t' }),
    );
    await render();
    // Each person is the default; the team's sign-in is a choice.
    expect(radio('member')?.getAttribute('aria-checked')).toBe('true');
    await act(async () => radio('team')!.click());
    expect(radio('team')?.getAttribute('aria-checked')).toBe('true');
    await act(async () => button('settings.tools.mcp.testConnection')!.click());
    expect(api.testMCPConnection).toHaveBeenCalledWith(
      expect.objectContaining({ owner: 'team' }),
      'token',
    );
    expect(api.testMCPConnection.mock.calls[0][0]).not.toHaveProperty(
      'connection_id',
    );
    state.events = [
      {
        id: 'e1',
        type: 'mcp.oauth.completed',
        scope: { id: 'task-1' },
        payload: { tools: [], tools_count: 0 },
      },
    ];
    await rerender();
    await act(async () => button('settings.tools.mcp.save')!.click());
    expect(api.saveMCPServer).toHaveBeenCalledWith(
      expect.objectContaining({
        owner: 'team',
        config: expect.objectContaining({ oauth_task_id: 'task-1' }),
      }),
      'token',
    );
    expect(api.createMemberTool).not.toHaveBeenCalled();
    expect(onServerSaved).toHaveBeenCalledWith('tool-t', {
      connectionId: 'conn-t',
    });
  });

  it('says when the team is already signed in to the server', async () => {
    setRole('owner');
    api.testMCPConnection.mockReturnValue(
      json(
        {
          success: false,
          error: 'account_already_connected',
          connection_id: 'conn-t',
          message: 'The team is already signed in to this server.',
        },
        false,
        409,
      ),
    );
    await render();
    await act(async () => radio('team')!.click());
    await act(async () => button('settings.tools.mcp.testConnection')!.click());
    expect(text()).toContain(
      'settings.connectors.team.errors.accountAlreadyConnected',
    );
    expect(button('settings.tools.mcp.save')!.disabled).toBe(true);
  });

  it('offers to sign in in Personal when the adder has no sign-in of their own', async () => {
    setRole('editor');
    api.createMemberTool.mockResolvedValue({
      success: false,
      error: 'connect_personal_first',
      connector_key: 'custom_mcp',
    });
    await render();
    await act(async () => button('settings.tools.mcp.save')!.click());
    expect(onServerSaved).not.toHaveBeenCalled();
    expect(text()).toContain(
      'settings.connectors.team.errors.connectPersonalFirst',
    );
    await act(async () =>
      button('settings.tools.mcp.team.signInInPersonal')!.click(),
    );
    expect(dispatch).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'workspace/switched',
        payload: expect.objectContaining({ id: 'personal' }),
      }),
    );
    // The Tools page in Personal opens the form again, filled in.
    expect(seen.location?.pathname).toBe('/settings/tools');
    expect(seen.location?.state).toEqual({
      newMcpServer: expect.objectContaining({
        server_url: 'https://mcp.tracker.dev/mcp',
        displayName: 'Tracker',
        auth_type: 'oauth',
      }),
    });
  });

  it("reconnects the team's own sign-in by its connection, never by a tool", async () => {
    setRole('admin');
    api.testMCPConnection.mockReturnValue(
      json({ success: false, requires_oauth: true, task_id: 'task-2' }),
    );
    await render({
      ...newServer,
      owner: 'team',
      connection_id: 'conn-t',
    });
    expect(radio('team')).toBeNull();
    await act(async () => button('settings.tools.mcp.testConnection')!.click());
    const body = api.testMCPConnection.mock.calls[0][0];
    expect(body).toEqual(
      expect.objectContaining({ owner: 'team', connection_id: 'conn-t' }),
    );
    expect(body).not.toHaveProperty('id');
  });

  it('keeps a team server saved without sign-in from turning into one', async () => {
    setRole('admin');
    await render({
      id: 'tool-1',
      displayName: 'Rates',
      server_url: 'https://mcp.rates.dev/mcp',
      auth_type: 'api_key',
      access: 'admin',
    });
    const types = Array.from(
      document.body.querySelectorAll('[data-testid="select-item"]'),
    ).map((item) => item.getAttribute('data-value'));
    expect(types).toEqual(['none', 'api_key', 'bearer']);
    expect(text()).toContain('settings.tools.mcp.team.oauthNewServerOnly');
  });
});
