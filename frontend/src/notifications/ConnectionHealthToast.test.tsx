import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'formatted' in opts ? `${key}:${opts.formatted}` : key,
  }),
}));

const server = vi.hoisted(() => ({
  catalog: [] as unknown[],
  connections: [] as unknown[],
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: vi.fn(async () => ({
      success: true,
      connectors: server.catalog,
    })),
    listConnections: vi.fn(async () => ({
      success: true,
      connections: server.connections,
    })),
  },
}));

const launch = vi.fn();
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import ConnectionHealthToast from './ConnectionHealthToast';
import notificationsReducer, { sseEventReceived } from './notificationsSlice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const DRIVE = { key: 'google_drive', name: 'Google Drive', auth_kind: 'oauth' };

describe('ConnectionHealthToast', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    localStorage.clear();
    launch.mockClear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    payload: Record<string, unknown>,
    connectionStatus = 'reconnect_needed',
  ) => {
    server.catalog = [DRIVE];
    server.connections = [{ id: 'conn-1', status: connectionStatus }];
    const store = configureStore({
      reducer: {
        notifications: notificationsReducer,
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
      preloadedState: {
        connectors: {
          enabled: true,
          loading: false,
          loaded: true,
          failed: false,
          catalog: [DRIVE],
          connections: [{ id: 'conn-1', status: connectionStatus }],
        },
        preference: { token: null },
      },
    } as Parameters<typeof configureStore>[0]);
    store.dispatch(
      sseEventReceived({
        id: 'e1',
        type: 'connection.reconnect_needed',
        ts: new Date().toISOString(),
        scope: { kind: 'connection', id: 'conn-1' },
        payload: {
          connection_id: 'conn-1',
          connector_key: 'google_drive',
          name: 'Google Drive',
          ...payload,
        },
      }),
    );
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <ConnectionHealthToast />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const title = () =>
    container.querySelector('[data-slot="toast-title"]')?.textContent;

  it('says which sources are paused', async () => {
    await render({ source_count: 3, tool_count: 0 });
    expect(title()).toBe('settings.connectors.health.reconnectSources:3');
  });

  it('says agents cannot use a tool-only connection', async () => {
    await render({ source_count: 0, tool_count: 2 });
    expect(title()).toBe('settings.connectors.health.reconnectTools:0');
  });

  it('reconnects in place and stays until it works', async () => {
    await render({ source_count: 1, tool_count: 1 });
    const link = container.querySelector('a')!;
    await act(async () => link.click());
    expect(launch).toHaveBeenCalledWith(DRIVE, {
      mode: 'reconnect',
      connectionId: 'conn-1',
    });
    expect(title()).toBe('settings.connectors.health.reconnectBoth:1');
  });

  it('links to the account on the Connectors page as the fallback', async () => {
    await render({ source_count: 1 });
    expect(container.querySelector('a')?.getAttribute('href')).toBe(
      '/settings/connectors?connector=google_drive&connection=conn-1',
    );
  });

  it('closes itself once the connection works again', async () => {
    await render({ source_count: 1 }, 'connected');
    expect(container.querySelector('[data-slot="toast"]')).toBeNull();
  });
});
