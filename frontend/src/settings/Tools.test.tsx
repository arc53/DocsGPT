import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const dispatch = vi.fn();
vi.mock('react-redux', () => ({
  useSelector: () => 'token',
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

describe('Tools', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
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
    await act(async () => {
      root.render(<Tools />);
    });
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

  it('disables the switch, keeping its label, for a shared tool without use_in_own', async () => {
    await render([viewerTool]);
    const sw = switchOf('vw');
    expect(sw.disabled).toBe(true);
    expect(card('vw').querySelector(`label[for="${sw.id}"]`)?.textContent).toBe(
      'settings.tools.inMyChats',
    );
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
    updateToolStatus.mockImplementation(() => jsonResponse({ success: true }));
    await act(async () => switchOf('ed').click());
    expect(switchOf('ed').getAttribute('aria-checked')).toBe('true');
    expect(dispatch).not.toHaveBeenCalled();
  });
});
