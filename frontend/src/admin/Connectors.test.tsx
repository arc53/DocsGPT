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

import { prefSlice } from '../preferences/preferenceSlice';
import Connectors from './Connectors';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const connector = (overrides: Record<string, unknown> = {}) => ({
  key: 'google_drive',
  name: 'Google Drive',
  icon: 'google-drive',
  publisher: 'built_in',
  auth_kind: 'oauth',
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
      configured: true,
      required_settings: [],
      connection_count: 0,
    }),
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

  const render = async () => {
    const store = configureStore({
      reducer: { preference: prefSlice.reducer },
    });
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
    expect(rows).toHaveLength(2);
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
    expect(container.textContent).toContain('admin.connectors.defaultKey');
    expect(container.textContent).toContain('docsgpt connectors reencrypt');
  });

  it('saves a connector toggle as a policy', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue(
      payload({
        connectors: [connector({ enabled: false })],
      }),
    );
    await render();
    const toggle = container.querySelector<HTMLButtonElement>(
      '[aria-label="Google Drive enabled"]',
    )!;
    await act(async () => toggle.click());
    expect(updateAdmin).toHaveBeenCalledWith(
      { policies: { google_drive: { enabled: false } } },
      null,
    );
    expect(
      container
        .querySelector('[aria-label="Google Drive enabled"]')
        ?.getAttribute('aria-checked'),
    ).toBe('false');
  });

  it('shows an error and keeps the page when a save fails', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue({ success: false });
    await render();
    await act(async () =>
      container.querySelector<HTMLButtonElement>('#allow-custom-mcp')!.click(),
    );
    expect(updateAdmin).toHaveBeenCalledWith({ allow_custom_mcp: false }, null);
    expect(container.textContent).toContain('Could not save the change.');
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('offers a retry when loading fails', async () => {
    getAdmin.mockRejectedValue(new Error('offline'));
    await render();
    expect(container.textContent).toContain('Failed to load connectors.');
  });
});
