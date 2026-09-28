import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

const getConnectorFiles = vi.fn();
vi.mock('../api/services/userService', () => ({
  default: {
    getConnectorFiles: (...args: unknown[]) => getConnectorFiles(...args),
  },
}));

const pickerToken = vi.fn();
const disconnect = vi.fn();
vi.mock('../api/services/connectorsService', () => ({
  default: {
    pickerToken: (...args: unknown[]) => pickerToken(...args),
    disconnect: (...args: unknown[]) => disconnect(...args),
    getCatalog: vi.fn().mockResolvedValue({ success: true, connectors: [] }),
    listConnections: vi
      .fn()
      .mockResolvedValue({ success: true, connections: [] }),
  },
}));

vi.mock('../components/ConnectorAuth', () => ({ default: () => null }));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import type { Connection } from '../connectors/types';
import { FilePicker } from './FilePicker';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const connection = (overrides: Partial<Connection> = {}): Connection => ({
  id: 'conn-1',
  connector_key: 'share_point',
  name: 'SharePoint',
  display_name: 'SharePoint',
  icon: 'sharepoint',
  account_label: 'lena@meridian.example',
  auth_kind: 'oauth',
  status: 'connected',
  server_url: null,
  last_error: null,
  created_at: null,
  updated_at: null,
  last_used_at: null,
  source_count: 0,
  tool_count: 0,
  ...overrides,
});

describe('FilePicker', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    getConnectorFiles.mockReset();
    pickerToken.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (provider: string, connections: Connection[]) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          catalog: [],
          connections,
          loading: false,
          loaded: true,
          failed: false,
        },
        preference: { token: null },
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <FilePicker
            provider={provider}
            token={null}
            onSelectionChange={() => undefined}
          />
        </Provider>,
      );
    });
  };

  it('shows a connection that needs signing in as a destructive alert', async () => {
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: false, reconnect: true }),
    });
    await render('google_drive', [
      connection({ connector_key: 'google_drive' }),
    ]);
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain('filePicker.sessionExpiredFor');
    expect(alert?.querySelector('svg')).not.toBeNull();
  });

  it('lists files with the connection id, never a session token', async () => {
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: true, files: [], next_page_token: null }),
    });
    await render('google_drive', [
      connection({ connector_key: 'google_drive' }),
    ]);
    const body = getConnectorFiles.mock.calls[0][0];
    expect(body.connection_id).toBe('conn-1');
    expect(body).not.toHaveProperty('session_token');
  });

  async function renderSharePoint() {
    pickerToken.mockResolvedValue({
      success: true,
      allows_shared_content: true,
    });
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: true, files: [], next_page_token: null }),
    });
    await render('share_point', [connection()]);
  }

  it('renders the drive switch as underline tabs with the active one marked', async () => {
    await renderSharePoint();
    const list = container.querySelector('[data-slot="tabs-list"]')!;
    expect(list.getAttribute('role')).toBe('tablist');
    expect(list.getAttribute('data-variant')).toBe('underline');
    const tabs = Array.from(
      list.querySelectorAll('[data-slot="tabs-trigger"][role="tab"]'),
    );
    expect(tabs.map((tab) => tab.textContent)).toEqual([
      'filePicker.myFiles',
      'filePicker.sharedWithMe',
    ]);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs[1].getAttribute('aria-selected')).toBe('false');
    // The file list below is the active tab's panel.
    const panel = container.querySelector('[role="tabpanel"]')!;
    expect(panel.id).toBe(tabs[0].getAttribute('aria-controls'));
  });

  it('shows the folder trail as a breadcrumb with the current folder as the page', async () => {
    await renderSharePoint();
    const trail = container.querySelector('nav[aria-label="breadcrumb"]');
    expect(trail).not.toBeNull();
    const page = trail?.querySelector('[data-slot="breadcrumb-page"]');
    expect(page?.textContent).toBe('filePicker.myFiles');
    expect(page?.getAttribute('title')).toBe('filePicker.myFiles');
    expect(trail?.querySelector('button[disabled]')).toBeNull();
  });

  it('offers an account switch when several accounts are connected', async () => {
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: true, files: [], next_page_token: null }),
    });
    pickerToken.mockResolvedValue({ success: true });
    await render('share_point', [
      connection(),
      connection({ id: 'conn-2', account_label: 'ops@meridian.example' }),
    ]);
    expect(container.textContent).toContain('filePicker.account');
  });

  it('shows nothing to browse without a connection', async () => {
    await render('confluence', []);
    expect(getConnectorFiles).not.toHaveBeenCalled();
    expect(container.querySelector('[data-slot="tabs-list"]')).toBeNull();
  });
});
