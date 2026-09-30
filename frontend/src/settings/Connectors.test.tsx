import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { Link, MemoryRouter, useLocation } from 'react-router-dom';

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

// The wizard is tested on its own; here only what it is opened with matters.
const launch = vi.hoisted(() => vi.fn());
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
}));

// The real drawer, with the props it is opened with recorded.
const drawerProps = vi.hoisted(() => vi.fn());
vi.mock('../connectors/ConnectionDrawer', async (importOriginal) => {
  const actual =
    await importOriginal<typeof import('../connectors/ConnectionDrawer')>();
  return {
    default: (props: Parameters<typeof actual.default>[0]) => {
      drawerProps(props);
      return <actual.default {...props} />;
    },
  };
});

import connectorsReducer from '../connectors/connectorsSlice';
import type { ConnectorDefinition } from '../connectors/types';
import Connectors from './Connectors';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.search}</output>;
}

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
            <Link
              data-testid="reconnect-link"
              to="/settings/connectors?connector=google_drive"
            />
            <Connectors />
            <LocationProbe />
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const card = (key: string) =>
    container.querySelector<HTMLButtonElement>(
      `[data-testid="connector-card-${key}"]`,
    );

  const badges = (key: string) =>
    Array.from(card(key)!.querySelectorAll<HTMLElement>('[data-slot="badge"]'));
  const footer = (key: string) =>
    card(key)!.querySelector('[data-slot="card-footer"]');

  it('renders every card state', async () => {
    await render();
    // Available: no badge and no footer; the tile itself is the action.
    expect(footer('telegram')).toBeNull();
    expect(badges('telegram').map((b) => b.textContent)).not.toContain(
      'settings.connectors.status.connect',
    );
    // The state leads the badge row; how many accounts is footer meta.
    expect(badges('google_drive')[0].textContent).toBe(
      'settings.connectors.status.connected',
    );
    expect(badges('google_drive')[0].dataset.variant).toBe('success');
    expect(footer('google_drive')!.textContent).toBe(
      'settings.connectors.status.connectedCount:2',
    );
    expect(badges('confluence')[0].textContent).toBe(
      'settings.connectors.status.reconnect',
    );
    expect(badges('confluence')[0].dataset.variant).toBe('warning');
    // A custom entry makes a new tool on each click: no state, no cue.
    expect(footer('custom_mcp')).toBeNull();
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

  it("names the one connected account in the card's footer", async () => {
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [
        {
          id: 'c1',
          connector_key: 'confluence',
          status: 'reconnect_needed',
          auth_kind: 'oauth',
          account_label: 'dana@meridian.example',
        },
      ],
    });
    await render();
    expect(footer('confluence')!.textContent).toBe('dana@meridian.example');
  });

  it('closes the toolbar with a rule and puts no plus on the page action', async () => {
    await render();
    const toolbar = container.querySelector('[data-slot="page-toolbar"]')!;
    expect(toolbar.querySelector('[data-slot="separator"]')).not.toBeNull();
    const action = Array.from(toolbar.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.addCustom',
    )!;
    expect(action.querySelectorAll('svg')).toHaveLength(1);
    expect(action.querySelector('svg')!.getAttribute('class')).toContain(
      'lucide-chevron-down',
    );
  });

  it('opens the drawer on the account a ?connection= link names', async () => {
    await render('/settings/connectors?connector=telegram&connection=a2');
    expect(drawerProps).toHaveBeenLastCalledWith(
      expect.objectContaining({
        connector: expect.objectContaining({ key: 'telegram' }),
        initialConnectionId: 'a2',
      }),
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

  const pills = () =>
    Array.from(
      container.querySelectorAll<HTMLElement>(
        '[data-slot="toggle-group-item"]',
      ),
    );
  const pill = (key: string) =>
    pills().find((item) =>
      item.textContent?.startsWith(`settings.connectors.filters.${key} `),
    );
  const location = () =>
    container.querySelector('[data-testid="location"]')!.textContent ?? '';

  it('filters by state, not category: All, Connected, Disconnected with counts', async () => {
    await render();
    expect(pills().map((item) => item.textContent)).toEqual([
      expect.stringMatching(/^settings\.connectors\.filters\.all \d+$/),
      'settings.connectors.filters.connected 1',
      'settings.connectors.filters.disconnected 1',
    ]);
    expect(container.textContent).not.toContain(
      'settings.connectors.categories',
    );
    // Three pills fit a phone: no Select stands in for them.
    expect(container.querySelector('[role="combobox"]')).toBeNull();
    // Page-toolbar filter: a sm group that hugs, drawing its own track.
    const group = container.querySelector('[data-slot="toggle-group"]')!;
    expect(group.className).toContain('bg-muted');
    expect(group.className).toContain('w-fit');
    expect(group.parentElement!.className).not.toContain('bg-muted');
    expect(
      group.querySelector('[data-slot="toggle-group-item"]')!.className,
    ).toContain('h-8');
  });

  it('filters to services with a working account', async () => {
    await render('/settings/connectors?filter=connected');
    expect(card('google_drive')).not.toBeNull();
    expect(card('confluence')).toBeNull();
    expect(card('telegram')).toBeNull();
  });

  it('filters to services whose account is signed out or disconnected', async () => {
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [
        {
          id: 'c1',
          connector_key: 'telegram',
          status: 'disconnected',
          account_label: 'Alerts bot',
        },
      ],
    });
    await render('/settings/connectors?filter=disconnected');
    expect(card('confluence')).not.toBeNull();
    expect(card('telegram')).not.toBeNull();
    expect(card('google_drive')).toBeNull();
  });

  it('keeps the filter in the address', async () => {
    await render();
    await act(async () => pill('disconnected')!.click());
    expect(location()).toContain('filter=disconnected');
    await act(async () => pill('all')!.click());
    expect(location()).not.toContain('filter=');
  });

  it('offers no state that nothing is in', async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [definition({})],
    });
    await render();
    // Only All would be left: no filter row at all.
    expect(pills()).toHaveLength(0);
  });

  it('shows the empty state when nothing is connected', async () => {
    service.getCatalog.mockResolvedValue({
      success: true,
      connectors: [definition({})],
    });
    await render('/settings/connectors?filter=connected');
    expect(container.textContent).toContain('settings.connectors.empty');
  });

  it('shows a narrowed list as a chip that clears it', async () => {
    await render('/settings/connectors?capability=sync');
    expect(container.textContent).toContain(
      'settings.connectors.capabilityChip.sync',
    );
    expect(card('telegram')).toBeNull();
    const clear = container.querySelector<HTMLButtonElement>(
      'button[aria-label="settings.connectors.capabilityFilter.clear"]',
    )!;
    await act(async () => clear.click());
    expect(container.textContent).not.toContain(
      'settings.connectors.capabilityChip.sync',
    );
    expect(location()).not.toContain('capability=');
    expect(card('telegram')).not.toBeNull();
  });

  describe('opened for Knowledge', () => {
    const S3 = definition({
      key: 's3',
      name: 'Amazon S3',
      category: 'files',
      capabilities: ['sync'],
      sync_ingestor: 's3',
      tool_templates: [],
      setup: { tools: 'off', sync: 'ask' },
    });

    beforeEach(() => {
      launch.mockClear();
      service.getCatalog.mockResolvedValue({
        success: true,
        connectors: [...CATALOG, S3],
      });
    });

    it('connects with syncing switched on from a sync-only list', async () => {
      await render('/settings/connectors?capability=sync');
      await act(async () => card('s3')!.click());
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ key: 's3' }),
        { purpose: 'knowledge' },
      );
    });

    it('leaves the choice off on a plain visit', async () => {
      await render();
      await act(async () => card('s3')!.click());
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ key: 's3' }),
        {},
      );
    });

    it("carries it through the connector's page", async () => {
      await render('/settings/connectors?capability=sync');
      await act(async () => card('google_drive')!.click());
      // No account of the user's own yet: the page offers Connect.
      const connect = Array.from(
        document.body.querySelectorAll<HTMLButtonElement>(
          '[role="dialog"] button',
        ),
      ).find(
        (b) => b.textContent?.trim() === 'settings.connectors.status.connect',
      )!;
      await act(async () => connect.click());
      expect(launch).toHaveBeenCalledWith(
        expect.objectContaining({ key: 'google_drive' }),
        { purpose: 'knowledge' },
      );
    });
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

  it('opens the page a ?connector= link names while already on the list', async () => {
    await render();
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    await act(async () =>
      container
        .querySelector<HTMLAnchorElement>('[data-testid="reconnect-link"]')!
        .click(),
    );
    const dialog = document.body.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain('Google Drive');
  });

  it('shows a retry when the catalog fails to load', async () => {
    service.getCatalog.mockResolvedValue({ success: false });
    await render();
    expect(container.textContent).toContain('settings.connectors.loadFailed');
  });
});
