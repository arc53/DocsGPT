import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { defaultValue?: string; count?: number }) =>
      opts?.count !== undefined ? `${key}:${opts.count}` : key,
  }),
}));

const service = vi.hoisted(() => ({
  getCatalog: vi.fn(),
  listConnections: vi.fn(),
  getConnection: vi.fn(),
  disconnect: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

import connectorsReducer from '../connectors/connectorsSlice';
import type { ConnectorDefinition } from '../connectors/types';
import Connectors from './Connectors';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const definition = (
  overrides: Partial<ConnectorDefinition>,
): ConnectorDefinition => ({
  key: 'telegram',
  name: 'Telegram',
  description: 'Send messages.',
  icon: 'tool_telegram',
  category: 'messaging',
  auth_kind: 'api_key',
  capabilities: ['write'],
  credential_fields: [],
  setup_fields: [],
  sync_ingestor: null,
  default_sync_frequency: 'weekly',
  tool_templates: ['telegram'],
  setup: { tools: 'auto', sync: 'off' },
  mcp_url: null,
  publisher: 'built_in',
  docs_url: null,
  oauth_scopes: [],
  available: true,
  disabled: false,
  needs_setup: false,
  missing_settings: [],
  connected_count: 0,
  connection_count: 0,
  status: null,
  state: 'available',
  credential_policy: 'choose',
  ...overrides,
});

const CATALOG = [
  definition({}),
  definition({
    key: 'google_drive',
    name: 'Google Drive',
    category: 'files',
    capabilities: ['sync'],
    state: 'connected',
    connected_count: 2,
    connection_count: 2,
    status: 'connected',
  }),
  definition({
    key: 'confluence',
    name: 'Confluence',
    category: 'knowledge',
    capabilities: ['sync'],
    state: 'reconnect',
    connection_count: 1,
    status: 'reconnect_needed',
  }),
  definition({
    key: 'share_point',
    name: 'SharePoint',
    category: 'files',
    state: 'needs_setup',
    available: false,
    needs_setup: true,
  }),
  definition({
    key: 'brave',
    name: 'Brave Search',
    category: 'search',
    state: 'disabled',
    available: false,
    disabled: true,
  }),
  definition({
    key: 'custom_mcp',
    name: 'MCP server',
    category: 'custom',
    publisher: 'custom',
    auth_kind: 'mcp',
    state: 'custom',
  }),
];

describe('Connectors page', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: CATALOG,
    });
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [],
    });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (path = '/settings/connectors') => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={[path]}>
            <Connectors />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const card = (key: string) =>
    container.querySelector<HTMLButtonElement>(
      `[data-testid="connector-card-${key}"]`,
    );

  it('renders every card state', async () => {
    await render();
    expect(card('telegram')!.textContent).toContain(
      'settings.connectors.status.connect',
    );
    expect(card('google_drive')!.textContent).toContain(
      'settings.connectors.status.connectedCount:2',
    );
    expect(card('confluence')!.textContent).toContain(
      'settings.connectors.status.reconnect',
    );
    expect(card('share_point')!.textContent).toContain(
      'settings.connectors.status.needsAdminSetup',
    );
    expect(card('brave')!.textContent).toContain(
      'settings.connectors.status.disabledByAdmin',
    );
    expect(card('brave')!.disabled).toBe(true);
    expect(card('custom_mcp')!.textContent).toContain(
      'settings.connectors.publisher.custom',
    );
  });

  it('sorts connections that need attention first', async () => {
    await render();
    const keys = Array.from(
      container.querySelectorAll('[data-testid^="connector-card-"]'),
    ).map((el) => el.getAttribute('data-testid'));
    expect(keys[0]).toBe('connector-card-confluence');
    expect(keys[1]).toBe('connector-card-google_drive');
    expect(keys[keys.length - 1]).toBe('connector-card-brave');
  });

  it('shows capability chips', async () => {
    await render();
    expect(card('google_drive')!.textContent).toContain(
      'settings.connectors.capability.sync',
    );
    expect(card('telegram')!.textContent).toContain(
      'settings.connectors.capability.write',
    );
  });

  it('filters to connected services', async () => {
    await render('/settings/connectors?filter=connected');
    expect(card('google_drive')).not.toBeNull();
    expect(card('confluence')).not.toBeNull();
    expect(card('telegram')).toBeNull();
  });

  it('shows the empty state when nothing is connected', async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [definition({})],
    });
    await render('/settings/connectors?filter=connected');
    expect(container.textContent).toContain('settings.connectors.empty');
  });

  it('shows a retry when the catalog fails to load', async () => {
    service.getCatalog.mockResolvedValue({ success: false });
    await render();
    expect(container.textContent).toContain('settings.connectors.loadFailed');
  });
});
