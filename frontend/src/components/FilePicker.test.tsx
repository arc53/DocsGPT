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

const authRendered = vi.hoisted(() => vi.fn());
vi.mock('../components/ConnectorAuth', () => ({
  default: () => {
    authRendered();
    return null;
  },
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts
        ? `${key}:${opts.formatted}`
        : opts && 'name' in opts
          ? `${key}:${opts.name}`
          : key,
  }),
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
    authRendered.mockReset();
    pickerToken.mockResolvedValue({ success: true });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  const render = async (
    provider: string,
    connections: Connection[],
    props: Partial<Parameters<typeof FilePicker>[0]> = {},
  ) => {
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
            {...props}
          />
        </Provider>,
      );
    });
  };

  const page = (files: object[], next: string | null = null) => ({
    json: async () => ({ success: true, files, next_page_token: next }),
  });
  const buttonNamed = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    );

  it('offers Reconnect when the sign-in expired', async () => {
    getConnectorFiles.mockResolvedValue({
      json: async () => ({ success: false, reconnect: true }),
    });
    const onReconnect = vi.fn();
    await render(
      'google_drive',
      [connection({ connector_key: 'google_drive' })],
      {
        connectionId: 'conn-1',
        onReconnect,
      },
    );
    expect(container.textContent).toContain(
      'settings.connectors.detail.expired',
    );
    await act(async () =>
      buttonNamed('settings.connectors.status.reconnect')!.click(),
    );
    expect(onReconnect).toHaveBeenCalled();
  });

  it('offers Retry when the listing failed', async () => {
    getConnectorFiles.mockResolvedValueOnce({
      json: async () => ({ success: false }),
    });
    await render('confluence', [connection({ connector_key: 'confluence' })], {
      connectionId: 'conn-1',
    });
    expect(container.textContent).toContain('filePicker.loadFailed');
    getConnectorFiles.mockResolvedValueOnce(
      page([{ id: 'f1', name: 'Runbook', type: 'page', modifiedTime: '' }]),
    );
    await act(async () => buttonNamed('retry')!.click());
    expect(container.textContent).toContain('Runbook');
  });

  it('says when a folder is empty', async () => {
    getConnectorFiles.mockResolvedValue(page([]));
    await render('confluence', [connection({ connector_key: 'confluence' })], {
      connectionId: 'conn-1',
    });
    expect(container.textContent).toContain('filePicker.emptyFolder');
  });

  it('lists items as check rows with a meta line, and counts the picked ones', async () => {
    getConnectorFiles.mockResolvedValue(
      page([
        {
          id: 'd1',
          name: 'Nordic carriers',
          type: 'folder',
          isFolder: true,
          modifiedTime: '2026-09-02T08:15:00Z',
        },
        {
          id: 'f1',
          name: 'Halvorsen MSA.pdf',
          type: 'application/pdf',
          size: 2_400_000,
          modifiedTime: '2026-09-12T09:30:00Z',
        },
      ]),
    );
    const onSelectionChange = vi.fn();
    await render('share_point', [connection()], {
      connectionId: 'conn-1',
      onSelectionChange,
    });
    // No table and no scroll cap: an outline card of rows.
    expect(container.querySelector('table')).toBeNull();
    const card = container.querySelector('[data-slot="card"]')!;
    expect(card.getAttribute('data-variant')).toBe('outline');
    expect(card.className).not.toMatch(/max-h-|overflow-y-auto|h-72/);
    expect(container.textContent).toContain('filePicker.folderMeta');
    expect(container.textContent).toContain('filePicker.fileMeta');
    // The search label rests on the modal surface.
    expect(container.querySelector('label')!.className).toContain('bg-card');
    const boxes =
      container.querySelectorAll<HTMLButtonElement>('[role="checkbox"]');
    await act(async () => boxes[1].click());
    expect(onSelectionChange).toHaveBeenLastCalledWith(['f1'], []);
    expect(container.textContent).toContain('filePicker.itemsSelected:1');
  });

  it('opens a folder from its chevron and shows the way back', async () => {
    getConnectorFiles.mockResolvedValue(
      page([
        {
          id: 'd1',
          name: 'Nordic carriers',
          type: 'folder',
          isFolder: true,
          modifiedTime: '',
        },
      ]),
    );
    const onSelectionChange = vi.fn();
    await render('share_point', [connection()], {
      connectionId: 'conn-1',
      onSelectionChange,
    });
    // At the root nothing repeats where this is.
    expect(container.querySelector('nav[aria-label="breadcrumb"]')).toBeNull();
    const open = container.querySelector<HTMLButtonElement>(
      'button[aria-label="filePicker.openFolder:Nordic carriers"]',
    )!;
    await act(async () => open.click());
    // Opening is not picking.
    expect(onSelectionChange).not.toHaveBeenCalled();
    expect(getConnectorFiles.mock.calls.at(-1)![0].folder_id).toBe('d1');
    const trail = container.querySelector('nav[aria-label="breadcrumb"]')!;
    const current = trail.querySelector('[data-slot="breadcrumb-page"]');
    expect(current?.textContent).toBe('Nordic carriers');
    expect(trail.textContent).toContain('filePicker.myFiles');
  });

  it('never shows the sign-in block when the caller supplies the account', async () => {
    getConnectorFiles.mockResolvedValue(page([]));
    await render('share_point', [connection()], { connectionId: 'conn-1' });
    expect(authRendered).not.toHaveBeenCalled();
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

  it('shows nothing to browse without a connection', async () => {
    await render('confluence', []);
    expect(getConnectorFiles).not.toHaveBeenCalled();
    expect(container.querySelector('[data-slot="tabs-list"]')).toBeNull();
  });
});
