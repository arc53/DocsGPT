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
    expect(container.textContent).toContain(
      'Set ENCRYPTION_SECRET_KEY before connecting services.',
    );
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

  it('reports a failed save in a toast and keeps the page', async () => {
    getAdmin.mockResolvedValue(payload());
    updateAdmin.mockResolvedValue({ success: false });
    await render();
    await act(async () =>
      container.querySelector<HTMLButtonElement>('#allow-custom-mcp')!.click(),
    );
    expect(updateAdmin).toHaveBeenCalledWith({ allow_custom_mcp: false }, null);
    expect(selectActionToast(store.getState())).toMatchObject({
      variant: 'destructive',
      message: 'Could not save the change.',
    });
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2);
  });

  it('saves one change at a time so a late response cannot win', async () => {
    getAdmin.mockResolvedValue(payload());
    const pending: ((value: unknown) => void)[] = [];
    updateAdmin.mockImplementation(
      () => new Promise((resolve) => pending.push(resolve)),
    );
    await render();
    const toggle = () =>
      container.querySelector<HTMLButtonElement>(
        '[aria-label="Google Drive enabled"]',
      )!;
    await act(async () => toggle().click());
    await act(async () =>
      container.querySelector<HTMLButtonElement>('#allow-custom-mcp')!.click(),
    );
    // The second save waits for the first.
    expect(updateAdmin).toHaveBeenCalledTimes(1);
    await act(async () =>
      pending[0](payload({ connectors: [connector({ enabled: false })] })),
    );
    expect(updateAdmin).toHaveBeenCalledTimes(2);
    await act(async () =>
      pending[1](
        payload({
          connectors: [connector({ enabled: false })],
          allow_custom_mcp: false,
        }),
      ),
    );
    expect(toggle().getAttribute('aria-checked')).toBe('false');
    expect(
      container
        .querySelector('#allow-custom-mcp')!
        .getAttribute('aria-checked'),
    ).toBe('false');
  });

  it('offers a retry when loading fails', async () => {
    getAdmin.mockRejectedValue(new Error('offline'));
    await render();
    expect(container.textContent).toContain('Failed to load connectors.');
  });
});
