import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

vi.mock('react-redux', () => ({
  useSelector: (selector: (state: unknown) => unknown) =>
    selector({ notifications: { recentEvents: [] }, preference: {} }),
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
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    document.body.innerHTML = '';
  });

  const render = async (overrides: Partial<typeof server> = {}) => {
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

  it('tells an editor whose tool it is and that their entry replaces it for everyone', async () => {
    await render({ access: 'editor', owner_label: 'Lena Fischer' });
    expect(text()).toContain(
      'settings.tools.mcp.sharedByEditor:{"owner":"Lena Fischer"}',
    );
    // Informative, not announced: a quiet default Alert with role="note".
    const note = Array.from(
      document.body.querySelectorAll<HTMLElement>('[data-slot="alert"]'),
    ).find((a) =>
      a.textContent?.includes('settings.tools.mcp.sharedCredentialsNotice'),
    );
    expect(note?.getAttribute('role')).toBe('note');
    expect(note?.dataset.variant).toBe('default');
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

  it('lets an editor rename an OAuth tool without reconnecting it', async () => {
    saveMCPServer.mockReturnValue(json({ success: true }));
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
    expect(save.disabled).toBe(false);
    await act(async () => save.click());
    expect(saveMCPServer).toHaveBeenCalledTimes(1);
    expect(testMCPConnection).not.toHaveBeenCalled();
  });

  it('keeps OAuth reconnect for the owner', async () => {
    await render({ auth_type: 'oauth', has_encrypted_credentials: false });
    expect(urlInput().disabled).toBe(false);
    expect(button('settings.tools.mcp.testConnection')).toBeDefined();
    expect(text()).not.toContain('settings.tools.mcp.sharedOAuthOwnerOnly');
  });
});
