import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

const { events } = vi.hoisted(() => ({ events: { recent: [] as unknown[] } }));
vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({
      notifications: { recentEvents: events.recent },
      preference: {},
    }),
}));
vi.mock('../preferences/preferenceSlice', () => ({
  selectToken: () => 'token',
}));
vi.mock('../notifications/notificationsSlice', () => ({
  selectRecentEvents: (state: { notifications: { recentEvents: unknown[] } }) =>
    state.notifications.recentEvents,
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      if (!opts || typeof opts !== 'object') return key;
      const { defaultValue: _d, interpolation: _i, ...rest } = opts;
      void _d;
      void _i;
      return Object.keys(rest).length ? `${key}:${JSON.stringify(rest)}` : key;
    },
  }),
}));

const testMCPConnection = vi.fn();
const saveMCPServer = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    testMCPConnection: (...args: unknown[]) => testMCPConnection(...args),
    saveMCPServer: (...args: unknown[]) => saveMCPServer(...args),
  },
}));

import MCPServerModal from './MCPServerModal';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const server = {
  id: 'tool-1',
  displayName: 'Carrier Rates MCP',
  server_url: 'https://mcp.dana-tools.dev/sse',
  auth_type: 'api_key',
  timeout: 30,
  oauth_scopes: '',
  has_encrypted_credentials: true,
  access: 'owner',
  owner_label: null as string | null,
};

const json = (body: unknown, ok = true, status = 200) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

describe('MCPServerModal', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    testMCPConnection.mockReset();
    saveMCPServer.mockReset();
    events.recent = [];
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
  });

  const render = async (
    overrides: Partial<typeof server> & { preset?: boolean } = {},
  ) => {
    await act(async () => {
      root.render(
        <MCPServerModal
          modalState="ACTIVE"
          setModalState={() => {}}
          server={{ ...server, ...overrides }}
          onServerSaved={() => {}}
        />,
      );
    });
  };

  const text = () => document.body.textContent ?? '';
  const button = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent === label)!;
  const typeInto = async (input: HTMLInputElement, value: string) => {
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        'value',
      )?.set?.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };
  const urlInput = () =>
    document.body.querySelector<HTMLInputElement>(
      'input[placeholder="https://example.com/mcp"]',
    )!;

  const excalidraw = {
    id: undefined,
    displayName: 'Excalidraw',
    server_url: 'https://mcp.excalidraw.com/mcp',
    auth_type: 'none',
    has_encrypted_credentials: false,
    preset: true,
  };

  it('tests and saves Excalidraw without field edits or sign-in', async () => {
    const open = vi.spyOn(window, 'open');
    testMCPConnection.mockReturnValue(
      json({ success: true, tools: [{ name: 'export_to_excalidraw' }] }),
    );
    saveMCPServer.mockReturnValue(json({ success: true }));
    await render(excalidraw);
    expect(urlInput().value).toBe(excalidraw.server_url);
    expect(document.body.querySelector('input[type="password"]')).toBeNull();
    expect(button('settings.tools.mcp.save').disabled).toBe(true);
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(testMCPConnection).toHaveBeenCalledWith(
      {
        config: {
          server_url: excalidraw.server_url,
          auth_type: 'none',
          timeout: 30,
        },
      },
      'token',
    );
    expect(text()).toContain('export_to_excalidraw');
    expect(button('settings.tools.mcp.save').disabled).toBe(false);
    await act(async () => button('settings.tools.mcp.save').click());
    expect(saveMCPServer).toHaveBeenCalledWith(
      {
        displayName: 'Excalidraw',
        config: {
          server_url: excalidraw.server_url,
          auth_type: 'none',
          timeout: 30,
        },
        status: true,
      },
      'token',
    );
    expect(open).not.toHaveBeenCalled();
  });

  it('keeps Excalidraw unsaved when its connection test fails', async () => {
    testMCPConnection.mockReturnValue(
      json({ success: false, message: 'Server unavailable' }),
    );
    await render(excalidraw);
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(text()).toContain('Server unavailable');
    expect(button('settings.tools.mcp.save').disabled).toBe(true);
    await act(async () => button('settings.tools.mcp.save').click());
    expect(saveMCPServer).not.toHaveBeenCalled();
  });

  it('tells an editor whose tool it is and that their entry replaces it for everyone', async () => {
    await render({ access: 'editor', owner_label: 'Lena Fischer' });
    expect(text()).toContain(
      'settings.tools.mcp.sharedByEditor:{"owner":"Lena Fischer"}',
    );
    // Informative, not announced: an info Alert with role="note".
    const note = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="alert"]'),
    ).find((a) =>
      a.textContent?.includes('settings.tools.mcp.sharedCredentialsNotice'),
    );
    expect(note?.getAttribute('role')).toBe('note');
    expect(note?.dataset.variant).toBe('info');
  });

  it('masks the API key and bearer token fields', async () => {
    await render();
    const key = document.body.querySelector<HTMLInputElement>(
      'input[placeholder="settings.tools.mcp.placeholders.apiKey"]',
    );
    expect(key?.type).toBe('password');
    expect(key?.value).toBe('');
  });

  it('falls back to "a teammate" without an owner label', async () => {
    await render({ access: 'editor', owner_label: null });
    expect(text()).toContain(
      'settings.tools.mcp.sharedByEditor:{"owner":"settings.tools.mcp.aTeammate"}',
    );
  });

  it("shows no sharing notices on the caller's own tool", async () => {
    await render();
    expect(text()).not.toContain('settings.tools.mcp.sharedByEditor');
    expect(text()).not.toContain('settings.tools.mcp.sharedCredentialsNotice');
  });

  it('hints that a saved key is kept when left empty', async () => {
    await render();
    expect(text()).toContain('settings.tools.mcp.savedKeyHint');
  });

  it('tests with the saved key while the server is unchanged', async () => {
    testMCPConnection.mockReturnValue(json({ success: true, tools: [] }));
    await render();
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(testMCPConnection).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'tool-1' }),
      'token',
    );
  });

  it('warns and requires a new key when the server host changes', async () => {
    await render({ access: 'editor', owner_label: 'Lena' });
    await typeInto(urlInput(), 'https://evil.example.com/sse');
    expect(text()).toContain(
      'settings.tools.mcp.serverChangedNotice:{"credential":"settings.tools.mcp.credentialNames.apiKey"}',
    );
    expect(text()).not.toContain('settings.tools.mcp.savedKeyHint');
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(testMCPConnection).not.toHaveBeenCalled();
    expect(text()).toContain('settings.tools.mcp.errors.apiKeyRequired');
  });

  it.each([
    ['a downgrade to http', 'http://mcp.dana-tools.dev/sse'],
    ['another port', 'https://mcp.dana-tools.dev:8443/sse'],
  ])('clears the saved key for %s', async (_label, url) => {
    await render();
    await typeInto(urlInput(), url);
    expect(text()).toContain('settings.tools.mcp.serverChangedNotice');
  });

  it('keeps the saved key when only the default port is spelled out', async () => {
    await render();
    await typeInto(urlInput(), 'https://mcp.dana-tools.dev:443/v2/sse');
    expect(text()).not.toContain('settings.tools.mcp.serverChangedNotice');
  });

  it('keeps the saved key for a path-only change on the same host', async () => {
    await render();
    await typeInto(urlInput(), 'https://mcp.dana-tools.dev/v2/sse');
    expect(text()).not.toContain('settings.tools.mcp.serverChangedNotice');
  });

  it("shows the server's save error in the error Alert", async () => {
    testMCPConnection.mockReturnValue(json({ success: true, tools: [] }));
    saveMCPServer.mockReturnValue(
      json({ success: false, message: 'Invalid server URL' }, false, 400),
    );
    await render();
    await act(async () => button('settings.tools.mcp.testConnection').click());
    await act(async () => button('settings.tools.mcp.save').click());
    expect(text()).toContain('Invalid server URL');
  });

  it('keeps a shared OAuth server read-only for an editor', async () => {
    await render({
      access: 'editor',
      owner_label: 'Lena',
      auth_type: 'oauth',
      has_encrypted_credentials: false,
    });
    expect(text()).toContain('settings.tools.mcp.sharedOAuthOwnerOnly');
    expect(urlInput().disabled).toBe(true);
    expect(button('settings.tools.mcp.testConnection')).toBeUndefined();
    const save = button('settings.tools.mcp.save');
    expect(save.disabled).toBe(true);
    await act(async () => save.click());
    expect(saveMCPServer).not.toHaveBeenCalled();
  });

  it('keeps OAuth reconnect for the owner', async () => {
    await render({ auth_type: 'oauth', has_encrypted_credentials: false });
    expect(urlInput().disabled).toBe(false);
    expect(button('settings.tools.mcp.testConnection')).toBeDefined();
    expect(text()).not.toContain('settings.tools.mcp.sharedOAuthOwnerOnly');
  });

  const alerts = () =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="alert"]'),
    );
  const alertWith = (key: string) =>
    alerts().find((a) => a.textContent?.includes(key));
  const advancedToggle = () =>
    button('settings.tools.mcp.advanced') as HTMLButtonElement | undefined;
  const timeoutInput = () =>
    document.body.querySelector<HTMLInputElement>('input[type="number"]');

  it('labels the Advanced toggle with a real key, above the fields it reveals', async () => {
    await render();
    expect(text()).not.toContain('modals.uploadDoc');
    const toggle = advancedToggle();
    expect(toggle).toBeDefined();
    expect(toggle!.getAttribute('aria-expanded')).toBe('false');
    // Folded: the fields wait in a closed, inert Collapsible.
    const body = document.getElementById(
      toggle!.getAttribute('aria-controls')!,
    )!;
    expect(body.dataset.state).toBe('closed');
    expect(body.hasAttribute('inert')).toBe(true);
    expect(body.contains(timeoutInput())).toBe(true);
    const chevron = toggle!.querySelector('svg');
    expect(chevron?.getAttribute('class')).not.toContain('rotate-90');

    await act(async () => toggle!.click());
    expect(toggle!.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
    expect(chevron?.getAttribute('class')).toContain('rotate-90');
    const input = timeoutInput()!;
    // The toggle comes first, then the fields it opened.
    expect(
      toggle!.compareDocumentPosition(input) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("doesn't repeat the server name label as its placeholder", async () => {
    await render();
    const nameInput = Array.from(
      document.body.querySelectorAll<HTMLInputElement>('input'),
    ).find((i) => i.value === 'Carrier Rates MCP')!;
    expect(nameInput.getAttribute('placeholder')).not.toBe(
      'settings.tools.mcp.serverName',
    );
  });

  it('says Save needs a successful test until one passes', async () => {
    testMCPConnection.mockReturnValue(json({ success: true, tools: [] }));
    await render();
    expect(button('settings.tools.mcp.save').disabled).toBe(true);
    expect(text()).toContain('settings.tools.mcp.testBeforeSave');
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(button('settings.tools.mcp.save').disabled).toBe(false);
    expect(text()).not.toContain('settings.tools.mcp.testBeforeSave');
  });

  it('lists discovered tools as ListRows under a counted heading', async () => {
    testMCPConnection.mockReturnValue(
      json({
        success: true,
        message: 'Connected',
        tools: [
          { name: 'get_rates', description: 'Carrier rates by lane' },
          { name: 'book_load' },
        ],
      }),
    );
    await render();
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(text()).toContain(
      'settings.tools.mcp.discoveredTools:{"count":2,"formatted":"2"}',
    );
    const rows = document.body.querySelectorAll(
      '[data-slot="list-rows"] [data-slot="list-row"]',
    );
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('get_rates');
    expect(rows[0].textContent).toContain('Carrier rates by lane');
    expect(alertWith('Connected')?.dataset.variant).toBe('success');
  });

  it('puts the save error at the top of the body', async () => {
    testMCPConnection.mockReturnValue(json({ success: true, tools: [] }));
    saveMCPServer.mockReturnValue(
      json({ success: false, message: 'Invalid server URL' }, false, 400),
    );
    await render();
    await act(async () => button('settings.tools.mcp.testConnection').click());
    await act(async () => button('settings.tools.mcp.save').click());
    const error = alertWith('Invalid server URL')!;
    expect(error.dataset.variant).toBe('destructive');
    expect(error.parentElement?.firstElementChild).toBe(error);
  });

  it('shows the OAuth wait as info and a blocked popup as a warning', async () => {
    testMCPConnection.mockReturnValue(
      json({ requires_oauth: true, task_id: 'task-1' }),
    );
    vi.spyOn(window, 'open').mockReturnValue(null);
    await render({ auth_type: 'oauth', has_encrypted_credentials: false });
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(
      alertWith('settings.tools.mcp.oauthInProgress')?.dataset.variant,
    ).toBe('info');

    events.recent = [
      {
        id: 'evt-1',
        type: 'mcp.oauth.awaiting_redirect',
        scope: { id: 'task-1' },
        payload: { authorization_url: 'https://auth.example.com/authorize' },
      },
    ];
    await render({ auth_type: 'oauth', has_encrypted_credentials: false });
    const blocked = alertWith('settings.tools.mcp.oauthPopupBlocked')!;
    expect(blocked.dataset.variant).toBe('warning');
    expect(blocked.textContent).toContain('settings.tools.mcp.openAuthPage');
  });

  it('leaves Alert icons unsized (the Alert sizes them)', async () => {
    testMCPConnection.mockReturnValue(
      json({ success: false, message: 'Refused' }),
    );
    await render();
    await act(async () => button('settings.tools.mcp.testConnection').click());
    expect(alertWith('Refused')?.dataset.variant).toBe('destructive');
    const icons = alerts().flatMap((a) =>
      Array.from(a.querySelectorAll(':scope > svg')),
    );
    expect(icons.length).toBeGreaterThan(0);
    for (const icon of icons) {
      expect(icon.getAttribute('class') ?? '').not.toMatch(/\bsize-/);
    }
  });
});
