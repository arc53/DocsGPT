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
    // No publisher jargon ("Preset", "Built in") on cards.
    expect(card('custom_mcp')!.textContent).not.toContain(
      'settings.connectors.publisher',
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
      'settings.connectors.capabilityPlain.sync',
    );
    expect(card('telegram')!.textContent).toContain(
      'settings.connectors.capabilityPlain.write',
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

  it('says when the composer narrowed the list, and clears it', async () => {
    await render('/settings/connectors?capability=sync');
    expect(container.textContent).toContain(
      'settings.connectors.capabilityFilter.sync',
    );
    expect(card('telegram')).toBeNull();
    const showAll = Array.from(container.querySelectorAll('button')).find(
      (button) =>
        button.textContent === 'settings.connectors.capabilityFilter.showAll',
    )!;
    await act(async () => showAll.click());
    expect(container.textContent).not.toContain(
      'settings.connectors.capabilityFilter.sync',
    );
    expect(card('telegram')).not.toBeNull();
  });

  it('only offers categories that have connectors', async () => {
    await render();
    const pills = Array.from(
      container.querySelectorAll('[data-slot="toggle-group-item"]'),
    ).map((item) => item.textContent);
    expect(pills).toContain('settings.connectors.categories.all');
    expect(pills).toContain('settings.connectors.categories.files');
    expect(pills).not.toContain('settings.connectors.categories.database');
  });

  it('offers no category that the capability filter would leave empty', async () => {
    await render('/settings/connectors?capability=sync');
    const pills = Array.from(
      container.querySelectorAll('[data-slot="toggle-group-item"]'),
    ).map((item) => item.textContent);
    expect(pills).toContain('settings.connectors.categories.files');
    // Telegram (messaging) cannot sync.
    expect(pills).not.toContain('settings.connectors.categories.messaging');
  });

  const ATLASSIAN = definition({
    key: 'mcp:atlassian',
    name: 'Jira & Confluence',
    description: 'Search and update Jira issues.',
    category: 'dev',
    auth_kind: 'mcp_oauth',
    capabilities: ['read', 'write'],
    publisher: 'preset',
    part_of: 'confluence',
  });

  it('shows one Confluence card that also does what its MCP part does', async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [...CATALOG, ATLASSIAN],
    });
    await render();
    expect(card('mcp:atlassian')).toBeNull();
    const confluence = card('confluence')!;
    expect(confluence.textContent).toContain(
      'settings.connectors.capabilityPlain.sync',
    );
    expect(confluence.textContent).toContain(
      'settings.connectors.capabilityPlain.write',
    );
  });

  it("finds the merged card by its part's name", async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [...CATALOG, ATLASSIAN],
    });
    await render();
    const input = container.querySelector<HTMLInputElement>(
      '#connector-search-input',
    )!;
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, 'jira');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(card('confluence')).not.toBeNull();
  });

  it('shows the part on its own when its parent is not listed', async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [...CATALOG.filter((c) => c.key !== 'confluence'), ATLASSIAN],
    });
    await render();
    expect(card('mcp:atlassian')).not.toBeNull();
  });

  it("opens the merged card's page with a section for its part", async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [...CATALOG, ATLASSIAN],
    });
    await render();
    await act(async () => card('confluence')!.click());
    expect(document.body.textContent).toContain('Jira & Confluence');
    expect(document.body.textContent).toContain(
      'settings.connectors.descriptions.mcp_atlassian',
    );
  });

  it('shows a retry when the catalog fails to load', async () => {
    service.getCatalog.mockResolvedValue({ success: false });
    await render();
    expect(container.textContent).toContain('settings.connectors.loadFailed');
  });
});
