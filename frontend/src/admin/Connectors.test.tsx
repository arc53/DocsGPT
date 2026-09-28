import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const getAdmin = vi.fn();
const updateAdmin = vi.fn();
vi.mock('../api/services/connectorsService', () => ({
  default: {
    getAdmin: (...args: unknown[]) => getAdmin(...args),
    updateAdmin: (...args: unknown[]) => updateAdmin(...args),
  },
}));

import actionToastReducer, {
  selectActionToast,
} from '../notifications/actionToastSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import Connectors from './Connectors';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const connector = (overrides: Record<string, unknown> = {}) => ({
  key: 'google_drive',
  name: 'Google Drive',
  icon: 'google-drive',
  publisher: 'built_in',
  auth_kind: 'oauth',
  capabilities: ['sync'],
  enabled: true,
  credential_mode: 'choose',
  configured: false,
  required_settings: [
    { name: 'GOOGLE_CLIENT_ID', set: true },
    { name: 'GOOGLE_CLIENT_SECRET', set: false },
  ],
  connection_count: 3,
  docs_url: null,
  mcp_url: null,
  ...overrides,
});

const MCP_ROW = connector({
  key: 'custom_mcp',
  name: 'MCP server',
  icon: 'mcp',
  publisher: 'custom',
  auth_kind: 'mcp',
  capabilities: ['read', 'write'],
  configured: true,
  required_settings: [],
  connection_count: 0,
});
const NOTION = {
  key: 'mcp_notion',
  name: 'Notion',
  icon: 'notion',
  publisher: 'preset',
  auth_kind: 'mcp_oauth',
  capabilities: ['read', 'write'],
  configured: true,
  required_settings: [],
  connection_count: 0,
};

const payload = (overrides: Record<string, unknown> = {}) => ({
  success: true,
  connectors: [
    connector(),
    connector({
      key: 'mcp_notion',
      name: 'Notion',
      icon: 'notion',
      publisher: 'preset',
      auth_kind: 'mcp_oauth',
      capabilities: ['read', 'write'],
      configured: true,
      required_settings: [],
      connection_count: 0,
    }),
    MCP_ROW,
  ],
  allow_custom_mcp: true,
  default_encryption_key: false,
  oauth_redirect_uri: 'https://docs.example/api/connectors/callback',
  mcp_redirect_uri: 'https://docs.example/api/mcp_server/callback',
  ...overrides,
});

describe('Admin Connectors', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getAdmin.mockReset();
    updateAdmin.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  let store: ReturnType<typeof makeStore>;
  const makeStore = () =>
    configureStore({
      reducer: {
        preference: prefSlice.reducer,
        actionToast: actionToastReducer,
      },
    });

  const render = async () => {
    store = makeStore();
    await act(async () => {
      root.render(
        <Provider store={store}>
          <Connectors />
        </Provider>,
      );
    });
  };

  it('lists each connector with its setup state and redirect URIs', async () => {
    getAdmin.mockResolvedValue(payload());
    await render();
    const rows = Array.from(container.querySelectorAll('tbody tr'));
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('Google Drive');
    expect(rows[0].textContent).toContain('Needs setup');
    expect(rows[0].textContent).toContain('Setup guide');
    expect(rows[1].textContent).toContain('Preset');
    expect(rows[1].textContent).toContain('Ready');
    expect(rows[1].textContent).not.toContain('Setup guide');
    expect(container.textContent).toContain(
      'https://docs.example/api/connectors/callback',
    );
  });

  it('warns when credentials use the default encryption key', async () => {
    getAdmin.mockResolvedValue(payload({ default_encryption_key: true }));
    await render();
    expect(container.textContent).toContain(
      'Set ENCRYPTION_SECRET_KEY before connecting services.',
    );
    expect(container.textContent).toContain('docsgpt connectors reencrypt');
  });

  it('saves a connector toggle as a policy', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue(
      payload({ connectors: [connector({ ...NOTION, enabled: false })] }),
    );
    await render();
    const toggle = () =>
      container.querySelector<HTMLButtonElement>(
        'table [aria-label="Notion enabled"]',
      )!;
    await act(async () => toggle().click());
    expect(updateAdmin).toHaveBeenCalledWith(
      { policies: { mcp_notion: { enabled: false } } },
      null,
    );
    expect(toggle().getAttribute('aria-checked')).toBe('false');
  });

  it('keeps a connector that needs setup off, and says why', async () => {
    getAdmin.mockResolvedValue(payload());
    await render();
    const drive = container.querySelector<HTMLButtonElement>(
      'table [aria-label="Google Drive enabled"]',
    )!;
    expect(drive.disabled).toBe(true);
  });

  it('shows no sharing policy for a sync-only connector', async () => {
    getAdmin.mockResolvedValue(payload());
    await render();
    const [drive, notion] = Array.from(container.querySelectorAll('tbody tr'));
    expect(drive.textContent).toContain('No tools');
    expect(
      notion.querySelector('[aria-label="Notion sharing policy"]'),
    ).not.toBeNull();
  });

  it('turns custom MCP servers off from their own row', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue(payload({ allow_custom_mcp: false }));
    await render();
    const mcp = () =>
      container.querySelector<HTMLButtonElement>(
        'table [aria-label="MCP server enabled"]',
      )!;
    await act(async () => mcp().click());
    expect(updateAdmin).toHaveBeenCalledWith(
      { allow_custom_mcp: false, policies: { custom_mcp: { enabled: false } } },
      null,
    );
    expect(mcp().getAttribute('aria-checked')).toBe('false');
    expect(container.querySelector('#allow-custom-mcp')).toBeNull();
  });

  it('lists connectors on phones and opens their controls in a sheet', async () => {
    getAdmin.mockResolvedValue(payload());
    await render();
    const rows = Array.from(
      container.querySelectorAll<HTMLButtonElement>(
        '[data-slot="list-row"] button',
      ),
    );
    expect(rows).toHaveLength(3);
    expect(rows[0].textContent).toContain('Off · 3 connections · No tools');
    await act(async () => rows[1].click());
    expect(
      document.body.querySelector('[data-slot="sheet-content"]'),
    ).not.toBeNull();
    expect(document.body.textContent).toContain('Shared tools use');
  });

  it('reports a failed save in a toast and keeps the page', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue({ success: false });
    await render();
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(
          'table [aria-label="Notion enabled"]',
        )!
        .click(),
    );
    expect(updateAdmin).toHaveBeenCalledWith(
      { policies: { mcp_notion: { enabled: false } } },
      null,
    );
    expect(selectActionToast(store.getState())).toMatchObject({
      variant: 'destructive',
      message: 'Could not save the change.',
    });
    expect(container.querySelectorAll('tbody tr')).toHaveLength(3);
  });

  it('saves one change at a time so a late response cannot win', async () => {
    getAdmin.mockResolvedValue(payload());
    const pending: ((value: unknown) => void)[] = [];
    updateAdmin.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    await render();
    const notion = () =>
      container.querySelector<HTMLButtonElement>(
        'table [aria-label="Notion enabled"]',
      )!;
    const mcp = () =>
      container.querySelector<HTMLButtonElement>(
        'table [aria-label="MCP server enabled"]',
      )!;
    await act(async () => notion().click());
    await act(async () => mcp().click());
    // The second save waits for the first.
    expect(updateAdmin).toHaveBeenCalledTimes(1);
    const off = connector({ ...NOTION, enabled: false });
    await act(async () => pending[0](payload({ connectors: [off, MCP_ROW] })));
    expect(updateAdmin).toHaveBeenCalledTimes(2);
    await act(async () =>
      pending[1](
        payload({ connectors: [off, MCP_ROW], allow_custom_mcp: false }),
      ),
    );
    expect(notion().getAttribute('aria-checked')).toBe('false');
    expect(mcp().getAttribute('aria-checked')).toBe('false');
  });

  it('offers a retry when loading fails', async () => {
    getAdmin.mockRejectedValue(new Error('offline'));
    await render();
    expect(container.textContent).toContain('Failed to load connectors.');
  });
});
