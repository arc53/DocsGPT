import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts && 'count' in opts ? `${key}:${opts.count}` : key,
  }),
}));

const service = vi.hoisted(() => ({
  createConnection: vi.fn(),
  setup: vi.fn(),
  reconnect: vi.fn(),
  getConnection: vi.fn(),
  getCatalog: vi.fn(),
  listConnections: vi.fn(),
  setToolPermissions: vi.fn(),
  pickerToken: vi.fn(),
  renameConnection: vi.fn(),
}));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

const mcpApi = vi.hoisted(() => ({
  testMCPConnection: vi.fn(),
  saveMCPServer: vi.fn(),
  getConfig: vi.fn(),
  getSourceDefaults: vi.fn(),
}));
vi.mock('../api/services/userService', async (importOriginal) => {
  const original = await importOriginal<{ default: object }>();
  return { default: { ...original.default, ...mcpApi } };
});

// The OAuth popup is covered by ConnectorAuth's own tests; here it only has
// to report a finished sign-in.
vi.mock('../components/ConnectorAuth', () => ({
  useConnectorAuth:
    ({
      onSuccess,
    }: {
      onSuccess: (data: { connection_id: string; user_email: string }) => void;
    }) =>
    () =>
      onSuccess({ connection_id: 'conn-drive', user_email: 'a@example.com' }),
}));
// Like the real picker, the selection is its own: a remount starts empty.
const googlePicker = vi.hoisted(() => ({ props: vi.fn() }));
vi.mock('../components/GoogleDrivePicker', () => ({
  default: (props: { clientId?: string | null }) => {
    googlePicker.props(props);
    return <div data-testid="google-picker" />;
  },
}));
vi.mock('../components/FilePicker', () => ({
  FilePicker: ({
    onSelectionChange,
    onFirstPickName,
    onReconnect,
  }: {
    onSelectionChange: (files: string[], folders?: string[]) => void;
    onFirstPickName?: (name: string) => void;
    onReconnect?: () => void;
  }) => (
    <>
      <button
        type="button"
        onClick={() => {
          onFirstPickName?.('Handbook');
          onSelectionChange([], ['folder-1']);
        }}
      >
        pick-folder
      </button>
      <button type="button" onClick={() => onSelectionChange(['file-9'], [])}>
        pick-file
      </button>
      <button type="button" onClick={onReconnect}>
        file-picker-reconnect
      </button>
    </>
  ),
}));

vi.mock('./RepoPicker', () => ({
  default: ({
    onChange,
    onReconnect,
  }: {
    onChange: (name: string) => void;
    onReconnect?: () => void;
  }) => (
    <>
      <button type="button" onClick={() => onChange('octocat/private')}>
        pick-repo
      </button>
      <button type="button" onClick={onReconnect}>
        picker-reconnect
      </button>
    </>
  ),
}));

vi.mock('./LinearPicker', async (importOriginal) => {
  const original = await importOriginal<typeof import('./LinearPicker')>();
  return {
    ...original,
    default: ({
      value,
      onChange,
    }: {
      value: import('./LinearPicker').LinearSelection;
      onChange: (selection: import('./LinearPicker').LinearSelection) => void;
    }) => (
      <button
        type="button"
        onClick={() =>
          onChange({
            ...value,
            teams: [{ id: 't1', key: 'ENG', name: 'Engineering' }],
          })
        }
      >
        pick-team
      </button>
    ),
  };
});

import notificationsReducer, {
  sseEventReceived,
} from '../notifications/notificationsSlice';
import {
  DEFAULT_RETRIEVAL_OPTIONS,
  optionsToConfig,
} from '../settings/components/RetrievalOptions';
import connectorsReducer from './connectorsSlice';
import ConnectWizard from './ConnectWizard';
import type { Connection, ConnectorDefinition } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

/** Where Open in Knowledge lands, with the source it opens. */
function KnowledgePage() {
  return <div>KNOWLEDGE{useLocation().search}</div>;
}

const base: ConnectorDefinition = {
  key: 'telegram',
  name: 'Telegram',
  description: 'Send messages.',
  icon: 'tool_telegram',
  category: 'messaging',
  auth_kind: 'api_key',
  capabilities: ['write'],
  credential_fields: [
    { key: 'token', label: 'Bot token', secret: true, required: true },
  ],
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
};

const drive: ConnectorDefinition = {
  ...base,
  key: 'google_drive',
  name: 'Google Drive',
  icon: 'drive',
  category: 'files',
  auth_kind: 'oauth',
  capabilities: ['sync'],
  credential_fields: [],
  sync_ingestor: 'google_drive',
  tool_templates: [],
  setup: { tools: 'off', sync: 'ask' },
};

// Sync only, with a pasted key: S3.
const s3: ConnectorDefinition = {
  ...base,
  key: 's3',
  name: 'Amazon S3',
  description: 'Sync documents from an S3 bucket.',
  icon: 's3',
  category: 'files',
  auth_kind: 'api_key',
  capabilities: ['sync'],
  credential_fields: [
    { key: 'secret', label: 'Secret key', secret: true, required: true },
  ],
  setup_fields: [
    { key: 'bucket', label: 'Bucket', secret: false, required: true },
  ],
  sync_ingestor: 's3',
  tool_templates: [],
  setup: { tools: 'off', sync: 'ask' },
};

const drawio: ConnectorDefinition = {
  ...base,
  key: 'mcp:drawio',
  name: 'draw.io',
  icon: 'drawio',
  auth_kind: 'mcp',
  capabilities: ['read'],
  credential_fields: [],
  tool_templates: ['mcp_tool'],
  mcp_url: 'https://mcp.draw.io/mcp',
  oauth_scopes: [],
  publisher: 'preset',
};

const github: ConnectorDefinition = {
  ...base,
  key: 'github',
  name: 'GitHub',
  icon: 'github',
  category: 'dev',
  auth_kind: 'api_key',
  capabilities: ['sync', 'read'],
  credential_fields: [
    {
      key: 'access_token',
      label: 'Personal access token',
      secret: true,
      required: true,
      hint: 'Fine-grained. <link>Create a token on GitHub</link>',
    },
  ],
  setup_fields: [
    { key: 'repo_url', label: 'Repository', secret: false, required: true },
  ],
  sync_ingestor: 'github',
  tool_templates: ['mcp_tool'],
  setup: { tools: 'ask', sync: 'ask' },
  mcp_url: 'https://api.githubcopilot.com/mcp/readonly',
  sign_in_methods: ['api_key'],
};

const TELEGRAM_TOOL = {
  id: 'tool-1',
  name: 'telegram',
  display_name: 'Telegram',
  status: true,
  credential_mode: 'owner',
  actions: [
    {
      name: 'telegram_send_message',
      description: 'Send',
      access: 'write',
      permission: 'ask',
    },
  ],
};

describe('ConnectWizard', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    Object.values(service).forEach((fn) => fn.mockReset());
    service.getCatalog.mockResolvedValue({ success: true, connectors: [] });
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [],
    });
    mcpApi.getConfig.mockResolvedValue({ json: async () => ({}) });
    mcpApi.getSourceDefaults.mockResolvedValue({ ok: false });
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    connector: ConnectorDefinition,
    onClose = vi.fn(),
    props: Partial<Parameters<typeof ConnectWizard>[0]> = {},
    connections: Connection[] = [],
    selectedDocs: { id: string }[] = [],
  ) => {
    if (connections.length)
      service.listConnections.mockResolvedValue({
        success: true,
        connections,
      });
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        notifications: notificationsReducer,
        // Applies the chat selection, as the real slice does.
        preference: (
          state: { token: null; selectedDocs: { id: string }[] } = {
            token: null,
            selectedDocs: [],
          },
          action: { type: string; payload?: unknown },
        ) =>
          action.type === 'preference/setSelectedDocs'
            ? { ...state, selectedDocs: action.payload as { id: string }[] }
            : state,
        conversation: (state = {}) => state,
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
        preference: { token: null, selectedDocs },
        conversation: {},
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/settings/connectors']}>
            <Routes>
              <Route
                path="/settings/connectors"
                element={
                  <ConnectWizard
                    connector={connector}
                    onClose={onClose}
                    {...props}
                  />
                }
              />
              <Route path="/c/new" element={<div>NEW_CHAT</div>} />
              <Route path="/settings/knowledge" element={<KnowledgePage />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    return store;
  };

  const click = async (text: string) => {
    const button = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === text);
    expect(button, `button ${text}`).toBeDefined();
    await act(async () => button!.click());
  };

  const title = () =>
    document.body.querySelector('[data-slot="modal-header"] h2')?.textContent;

  const button = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === text);

  const successAlert = () =>
    document.body.querySelector<HTMLElement>(
      '[role="status"][data-slot="alert"]',
    );

  const knowledgeSwitch = () =>
    document.body.querySelector<HTMLButtonElement>('[id^="knowledge-"]');

  /** The sync-only setup's two ways on, as radios. */
  const choice = (label: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[role="radiogroup"] [role="radio"]',
      ),
    ).find((radio) => radio.textContent?.includes(label));
  const syncNowCard = () => choice('settings.connectors.wizard.syncNow')!;
  const justConnectCard = () =>
    choice('settings.connectors.wizard.justConnect')!;
  /** The footer's buttons, in order, by label. */
  const footer = () =>
    Array.from(
      document.body.querySelectorAll<HTMLButtonElement>(
        '[data-slot="modal-footer"] button',
      ),
    ).map((b) => `${b.textContent?.trim()}:${b.dataset.variant}`);

  const typeInto = async (input: HTMLInputElement, value: string) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      'value',
    )!.set!;
    await act(async () => {
      setter.call(input, value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  /** The credential form's secret field (a key or a token). */
  const keyField = () =>
    document.body.querySelector<HTMLInputElement>('input[type="password"]');

  /** Types a key into the credential form and presses Connect. */
  const connectWithKey = async (key: string) => {
    await typeInto(keyField()!, key);
    await click('settings.connectors.status.connect');
  };

  /** The setup call succeeds with these sources and tools. */
  const setupOk = (
    sources: { id: string; name: string }[] = [],
    tools: unknown[] = [],
  ) => service.setup.mockResolvedValue({ success: true, tools, sources });

  it('connects an API-key service and creates its tools with no further questions', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    setupOk([], [TELEGRAM_TOOL]);
    await render(base);
    await connectWithKey('123:abc');
    expect(service.createConnection).toHaveBeenCalledWith(
      { connector_key: 'telegram', credentials: { token: '123:abc' } },
      null,
    );
    expect(service.setup).toHaveBeenCalledWith(
      'conn-1',
      { create_tools: true },
      null,
    );
    // Straight to the summary: no sync step for a tool-only service.
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.doneTitle',
    );
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.toolsHeading:1',
    );
    // The tools open under a link toggle with the count, no frame: the cards
    // line up with the success Alert above.
    const toggle = button('settings.connectors.wizard.toolsHeading:1')!;
    expect(toggle.dataset.variant).toBe('link');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    const body = document.getElementById(
      toggle.getAttribute('aria-controls')!,
    )!;
    expect(body.dataset.slot).toBe('collapsible');
    expect(body.dataset.state).toBe('closed');
    await act(async () => toggle.click());
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(body.dataset.state).toBe('open');
  });

  it('names the account when the user gives it a name', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    service.renameConnection.mockResolvedValue({ success: true });
    setupOk();
    await render(base);
    await typeInto(keyField()!, '123:abc');
    await typeInto(
      document.body.querySelector<HTMLInputElement>('#connect-account-name')!,
      ' Alerts bot ',
    );
    await click('settings.connectors.status.connect');
    expect(service.renameConnection).toHaveBeenCalledWith(
      'conn-1',
      'Alerts bot',
      null,
    );
  });

  it('leaves an unnamed account alone', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    setupOk();
    await render(base);
    await connectWithKey('123:abc');
    expect(service.renameConnection).not.toHaveBeenCalled();
  });

  it('names a signed-in account after the sign-in', async () => {
    service.renameConnection.mockResolvedValue({ success: true });
    await render(drive);
    await typeInto(
      document.body.querySelector<HTMLInputElement>('#connect-account-name')!,
      'Work',
    );
    await click('settings.connectors.wizard.signIn');
    expect(service.renameConnection).toHaveBeenCalledWith(
      'conn-drive',
      'Work',
      null,
    );
  });

  it('shows the default-key refusal in the form', async () => {
    service.createConnection.mockResolvedValue({
      success: false,
      code: 'encryption_key_default',
    });
    await render(base);
    await connectWithKey('x');
    expect(document.body.textContent).toContain(
      'settings.connectors.error.defaultKey',
    );
  });

  it('finishes setting up without syncing on Just connect', async () => {
    const onClose = vi.fn();
    await render(drive, onClose, { purpose: 'knowledge' });
    await click('settings.connectors.wizard.signIn');
    expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
    // No Skip: the account exists, one submit says what it does.
    expect(button('settings.connectors.wizard.skip')).toBeUndefined();
    expect(button('modals.uploadDoc.train')).toBeDefined();
    await act(async () => justConnectCard().click());
    // The title stays put while the choice changes.
    expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
    await click('settings.connectors.wizard.finishSetup');
    expect(title()).toBe('settings.connectors.wizard.doneTitle');
    expect(service.setup).not.toHaveBeenCalled();
    await click('settings.connectors.wizard.done');
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it('syncs the picked folder named after it', async () => {
    setupOk([{ id: 'src-1', name: 'Handbook' }]);
    const onSynced = vi.fn();
    await render(drive, vi.fn(), { purpose: 'knowledge', onSynced });
    await click('settings.connectors.wizard.signIn');
    await click('pick-folder');
    await click('modals.uploadDoc.train');
    // The opener tracks the new source's ingest, like an upload's.
    expect(onSynced).toHaveBeenCalledWith(['src-1']);
    const [id, body, , key] = service.setup.mock.calls[0];
    expect(id).toBe('conn-drive');
    expect(body.sync).toEqual({
      items: { file_ids: [], folder_ids: ['folder-1'] },
      frequency: 'weekly',
      name: 'Handbook',
      config: optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS),
    });
    expect(typeof key).toBe('string');
    // The summary is a polite success notice.
    expect(successAlert()?.textContent).toContain(
      'settings.connectors.wizard.doneSources',
    );
  });

  describe('Sync into Knowledge', () => {
    it('asks a sync-only service with two choices, Sync content now picked from any entry', async () => {
      // Opened from Connectors: no purpose.
      await render(drive);
      await click('settings.connectors.wizard.signIn');
      expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
      // Not a switch: two radios in one group.
      expect(knowledgeSwitch()).toBeNull();
      expect(
        document.body.querySelectorAll('[role="radiogroup"] [role="radio"]'),
      ).toHaveLength(2);
      expect(syncNowCard().getAttribute('aria-checked')).toBe('true');
      expect(justConnectCard().getAttribute('aria-checked')).toBe('false');
      expect(syncNowCard().textContent).toContain(
        'settings.connectors.wizard.syncNowDescription',
      );
      expect(justConnectCard().textContent).toContain(
        'settings.connectors.wizard.justConnectDescription',
      );
      // The form sits under the choice, open.
      const form = document.body
        .querySelector('[role="radiogroup"]')!
        .parentElement!.querySelector('[data-slot="collapsible"]')!;
      expect(form.getAttribute('data-state')).toBe('open');
      expect(form.textContent).toContain('pick-folder');
      expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
    });

    it('folds the form away on Just connect, keeping what was picked', async () => {
      setupOk([{ id: 'src-1', name: 'Handbook' }]);
      await render(drive);
      await click('settings.connectors.wizard.signIn');
      await click('pick-folder');
      await act(async () => justConnectCard().click());
      expect(justConnectCard().getAttribute('aria-checked')).toBe('true');
      const form = document.body.querySelector(
        '[role="radiogroup"] ~ [data-slot="collapsible"]',
      )!;
      expect(form.getAttribute('data-state')).toBe('closed');
      expect(button('settings.connectors.wizard.finishSetup')).toBeDefined();
      await act(async () => syncNowCard().click());
      expect(form.getAttribute('data-state')).toBe('open');
      // Still picked: the form was only folded.
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][1].sync.items).toEqual({
        file_ids: [],
        folder_ids: ['folder-1'],
      });
    });

    it('describes the service and the key it connected with', async () => {
      service.createConnection.mockResolvedValue({
        success: true,
        connection: { id: 'conn-s3', account_label: '…1c26' },
      });
      await render(s3);
      await connectWithKey('secret');
      const header = document.body.querySelector('[data-slot="modal-header"]')!;
      expect(header.textContent).toContain(
        'settings.connectors.descriptions.s3',
      );
      expect(header.textContent).toContain(
        'settings.connectors.wizard.connectedWithKey',
      );
      expect(header.textContent).not.toContain(
        'settings.connectors.wizard.signedInAs',
      );
      expect(syncNowCard().getAttribute('aria-checked')).toBe('true');
    });

    it('keeps the two switches for a service that offers tools and sync', async () => {
      service.createConnection.mockResolvedValue({
        success: true,
        connection: { id: 'conn-gh', account_label: 'octocat' },
      });
      await render(github);
      await connectWithKey('github_pat');
      expect(document.body.querySelector('[role="radiogroup"]')).toBeNull();
      expect(knowledgeSwitch()).not.toBeNull();
      expect(
        document.body.querySelector('[data-slot="modal-header"]')!.textContent,
      ).toContain('settings.connectors.wizard.signedInAs');
    });

    it('sends the advanced retrieval settings with the sync', async () => {
      setupOk();
      await render(drive, vi.fn(), { purpose: 'knowledge' });
      await click('settings.connectors.wizard.signIn');
      const toggle = button('settings.connectors.wizard.retrievalSettings')!;
      expect(toggle.getAttribute('aria-expanded')).toBe('false');
      await act(async () => toggle.click());
      expect(toggle.getAttribute('aria-expanded')).toBe('true');
      await typeInto(
        document.body.querySelector<HTMLInputElement>('#retrieval-chunks')!,
        '9',
      );
      await click('pick-folder');
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][1].sync.config).toEqual(
        optionsToConfig({
          ...DEFAULT_RETRIEVAL_OPTIONS,
          retrieval: { ...DEFAULT_RETRIEVAL_OPTIONS.retrieval, chunks: 9 },
        }),
      );
    });

    it('leaves filtering to after the first sync, and offers no screening', async () => {
      await render(drive, vi.fn(), { purpose: 'knowledge' });
      await click('settings.connectors.wizard.signIn');
      await click('settings.connectors.wizard.retrievalSettings');
      expect(document.body.querySelector('#retrieval-prescreen')).toBeNull();
      expect(document.body.textContent).toContain(
        'settings.sources.retrievalOptions.createHint',
      );
    });

    it('blocks the sync while the prescreen settings do not add up, and shows them', async () => {
      // The admin's defaults screen 40 candidates.
      mcpApi.getSourceDefaults.mockResolvedValue({
        ok: true,
        json: async () => ({
          success: true,
          retrieval: {
            prescreen: {
              candidate_k: 40,
              model: null,
              batch_size: 10,
              max_keep: 8,
            },
          },
        }),
      });
      await render(drive, vi.fn(), { purpose: 'knowledge' });
      await click('settings.connectors.wizard.signIn');
      await click('pick-folder');
      await click('settings.connectors.wizard.retrievalSettings');
      expect(document.body.querySelector('#retrieval-prescreen')).toBeNull();
      // More chunks than prescreen candidates.
      await typeInto(
        document.body.querySelector<HTMLInputElement>('#retrieval-chunks')!,
        '50',
      );
      expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
      // The rows come back so the conflict can be fixed here.
      expect(
        document.body.querySelector('#retrieval-prescreen'),
      ).not.toBeNull();
    });

    it('is not asked about when syncing more from an account', async () => {
      await render(drive, vi.fn(), {
        mode: 'sync',
        connectionId: 'conn-drive',
      });
      expect(knowledgeSwitch()).toBeNull();
      expect(document.body.querySelector('[role="radiogroup"]')).toBeNull();
      expect(document.body.textContent).toContain('pick-folder');
      expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
    });

    it('is not offered by a service that does not sync', async () => {
      service.createConnection.mockResolvedValue({
        success: true,
        connection: { id: 'conn-1' },
      });
      setupOk();
      await render(base, vi.fn(), { purpose: 'knowledge' });
      await connectWithKey('t');
      expect(knowledgeSwitch()).toBeNull();
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.syncLater',
      );
    });
  });

  describe('header and ending', () => {
    it('puts the service tile beside the title and its description under it', async () => {
      await render(base);
      const header = document.body.querySelector('[data-slot="modal-header"]')!;
      expect(header.querySelector('[data-slot="avatar"]')).not.toBeNull();
      expect(header.textContent).toContain(
        'settings.connectors.wizard.connectTitle',
      );
      expect(header.textContent).toContain(
        'settings.connectors.descriptions.telegram',
      );
      // The body no longer repeats a tile row.
      const body = document.body.querySelector('[role="dialog"]')!;
      expect(body.querySelectorAll('[data-slot="avatar"]')).toHaveLength(1);
    });

    it('closes with nothing connected on a plain cancel', async () => {
      const onClose = vi.fn();
      await render(base, onClose);
      await click('cancel');
      expect(onClose).toHaveBeenCalledWith(false);
    });

    it('closes as connected once an account was made', async () => {
      service.createConnection.mockResolvedValue({
        success: true,
        connection: { id: 'conn-1', account_label: 'Alerts bot' },
      });
      setupOk();
      const onClose = vi.fn();
      await render(base, onClose);
      await connectWithKey('t');
      expect(successAlert()?.getAttribute('role')).toBe('status');
      expect(successAlert()?.textContent).toContain(
        'settings.connectors.wizard.doneSummaryNone',
      );
      await click('settings.connectors.wizard.done');
      expect(onClose).toHaveBeenCalledWith(true);
    });

    it('never says who is connected before it knows', async () => {
      setupOk();
      await render(drive);
      await click('settings.connectors.wizard.signIn');
      await act(async () => justConnectCard().click());
      await click('settings.connectors.wizard.finishSetup');
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.doneSummaryNone',
      );
      expect(successAlert()?.textContent).toContain(
        'settings.connectors.wizard.syncLater',
      );
    });

    it('offers Cancel and Add to Knowledge when syncing more', async () => {
      const onClose = vi.fn();
      await render(drive, onClose, {
        mode: 'sync',
        connectionId: 'conn-drive',
      });
      expect(button('settings.connectors.wizard.skip')).toBeUndefined();
      expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
      await click('cancel');
      expect(onClose).toHaveBeenCalledWith(false);
    });
  });

  it('closes as done after syncing more from an account', async () => {
    setupOk([{ id: 'src-1', name: 'Handbook' }]);
    const onClose = vi.fn();
    await render(drive, onClose, { mode: 'sync', connectionId: 'conn-drive' });
    await click('pick-folder');
    await click('modals.uploadDoc.train');
    await click('settings.connectors.wizard.done');
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it("uses Google's picker with the client id the server offers", async () => {
    await render(
      { ...drive, picker_client_id: '999-server.apps.example' },
      vi.fn(),
      { mode: 'sync', connectionId: 'conn-drive' },
    );
    expect(
      document.body.querySelector('[data-testid="google-picker"]'),
    ).not.toBeNull();
    expect(googlePicker.props).toHaveBeenLastCalledWith(
      expect.objectContaining({ clientId: '999-server.apps.example' }),
    );
  });

  describe('which account', () => {
    const account = (id: string, label: string) => ({
      id,
      connector_key: 'google_drive',
      name: 'Google Drive',
      display_name: null,
      icon: 'drive',
      account_label: label,
      auth_kind: 'oauth' as const,
      status: 'connected' as const,
      server_url: null,
      last_error: null,
      created_at: null,
      updated_at: null,
      last_used_at: null,
      source_count: 0,
      tool_count: 0,
    });

    it('asks which account first when the service has several', async () => {
      await render(drive, vi.fn(), { mode: 'sync', purpose: 'knowledge' }, [
        account('a1', 'lena@meridian.example'),
        account('a2', 'ops@meridian.example'),
      ]);
      const field = document.body.querySelector(
        '[role="dialog"] [role="combobox"]',
      );
      expect(field?.textContent).toContain('lena@meridian.example');
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.account',
      );
      await click('pick-folder');
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][0]).toBe('a1');
    });

    it('names the one account in the description', async () => {
      await render(drive, vi.fn(), { mode: 'sync' }, [
        account('a1', 'lena@meridian.example'),
      ]);
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.account',
      );
      const header = document.body.querySelector('[data-slot="modal-header"]')!;
      expect(header.textContent).toContain('lena@meridian.example');
    });
  });

  it('reconnects from a picker whose sign-in expired, then picks up again', async () => {
    service.reconnect.mockResolvedValue({
      success: true,
      connection: { id: 'conn-gh' },
    });
    const onClose = vi.fn();
    await render(github, onClose, { mode: 'sync', connectionId: 'conn-gh' });
    await click('picker-reconnect');
    expect(title()).toBe('settings.connectors.wizard.reconnectTitle');
    await typeInto(keyField()!, 'github_pat_new');
    await click('settings.connectors.status.reconnect');
    expect(service.reconnect).toHaveBeenCalledWith(
      'conn-gh',
      { credentials: { access_token: 'github_pat_new' } },
      null,
    );
    // Back on the picker it came from.
    expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
    expect(document.body.textContent).toContain('pick-repo');
    await click('cancel');
    expect(onClose).toHaveBeenCalledWith(true);
  });

  it('starts a file picker over after a reconnect, with nothing picked', async () => {
    setupOk([{ id: 'src-3', name: 'Report' }]);
    await render(drive, vi.fn(), { mode: 'sync', connectionId: 'conn-drive' });
    await click('pick-folder');
    expect(button('modals.uploadDoc.train')?.disabled).toBe(false);
    await click('file-picker-reconnect');
    expect(title()).toBe('settings.connectors.wizard.reconnectTitle');
    await click('settings.connectors.wizard.signIn');
    // Back on the picker, which remounted empty: the wizard holds nothing.
    expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
    expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
    await click('pick-file');
    await click('modals.uploadDoc.train');
    expect(service.setup.mock.calls[0][1].sync.items).toEqual({
      file_ids: ['file-9'],
      folder_ids: [],
    });
  });

  it('opens a new chat over no sources from Try it in chat', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    setupOk([], [TELEGRAM_TOOL]);
    const onClose = vi.fn();
    const store = await render(base, onClose, {}, [], [{ id: 'old-chat-doc' }]);
    await connectWithKey('t');
    // Tools on: Done and Try it in chat.
    expect(footer()).toEqual([
      'settings.connectors.wizard.done:ghost',
      'settings.connectors.wizard.tryInChat:default',
    ]);
    await click('settings.connectors.wizard.tryInChat');
    expect(onClose).toHaveBeenCalled();
    expect(document.body.textContent).toContain('NEW_CHAT');
    // The last chat's sources don't come along.
    expect(
      (store.getState() as { preference: { selectedDocs: unknown[] } })
        .preference.selectedDocs,
    ).toEqual([]);
  });

  it.each([
    ['reconnect', 'settings.connectors.wizard.setupReconnect'],
    ['disabled', 'settings.connectors.wizard.setupDisabled'],
    ['tools_unavailable', 'settings.connectors.wizard.toolsUnavailable'],
    ['writes_forbidden', 'settings.connectors.github.writesForbidden'],
    ['something_new', 'settings.connectors.detail.syncFailed'],
  ])("words a setup refused as %s in the UI's language", async (code, key) => {
    service.setup.mockResolvedValue({
      success: false,
      code,
      error: 'English words from the server',
    });
    await render(drive);
    await click('settings.connectors.wizard.signIn');
    await click('pick-folder');
    await click('modals.uploadDoc.train');
    expect(document.body.textContent).toContain(key);
    expect(document.body.textContent).not.toContain(
      'English words from the server',
    );
  });

  describe('done footer', () => {
    it('opens the new source in Knowledge once content is synced', async () => {
      setupOk([{ id: 'src-1', name: 'Handbook' }]);
      const onClose = vi.fn();
      await render(drive, onClose);
      await click('settings.connectors.wizard.signIn');
      await click('pick-folder');
      await click('modals.uploadDoc.train');
      expect(footer()).toEqual([
        'settings.connectors.wizard.done:ghost',
        'settings.connectors.openInKnowledge:default',
      ]);
      // The alert reports; it gives no directions.
      expect(successAlert()?.textContent).not.toContain(
        'settings.connectors.wizard.syncLater',
      );
      await click('settings.connectors.openInKnowledge');
      expect(onClose).toHaveBeenCalledWith(true);
      expect(document.body.textContent).toContain('KNOWLEDGE?source=src-1');
    });

    it('offers Sync content when nothing synced, and syncs in place', async () => {
      setupOk([{ id: 'src-1', name: 'Handbook' }]);
      await render(drive, vi.fn(), {}, [
        {
          id: 'conn-drive',
          connector_key: 'google_drive',
          status: 'connected',
        } as Connection,
        {
          id: 'conn-other',
          connector_key: 'google_drive',
          status: 'connected',
        } as Connection,
      ]);
      await click('settings.connectors.wizard.signIn');
      await act(async () => justConnectCard().click());
      await click('settings.connectors.wizard.finishSetup');
      expect(footer()).toEqual([
        'settings.connectors.syncContent:outline',
        'settings.connectors.wizard.done:default',
      ]);
      expect(successAlert()?.textContent).toContain(
        'settings.connectors.wizard.syncLater',
      );
      await click('settings.connectors.syncContent');
      // The wizard's sync step, on the account it just connected.
      expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
      expect(document.body.querySelector('[role="radiogroup"]')).toBeNull();
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.account',
      );
      await click('pick-folder');
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][0]).toBe('conn-drive');
      expect(title()).toBe('settings.connectors.wizard.doneTitle');
    });

    it('starts Sync content with nothing picked, even after a folded pick', async () => {
      setupOk([{ id: 'src-2', name: 'Notes' }]);
      await render(drive, vi.fn(), {}, [
        {
          id: 'conn-drive',
          connector_key: 'google_drive',
          status: 'connected',
        } as Connection,
      ]);
      await click('settings.connectors.wizard.signIn');
      // Picked, then folded away by Just connect: nothing is set up.
      await click('pick-folder');
      await act(async () => justConnectCard().click());
      await click('settings.connectors.wizard.finishSetup');
      expect(service.setup).not.toHaveBeenCalled();
      await click('settings.connectors.syncContent');
      // The picker starts over, and so does what the wizard would sync.
      expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
      await click('pick-file');
      expect(button('modals.uploadDoc.train')?.disabled).toBe(false);
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][1].sync.items).toEqual({
        file_ids: ['file-9'],
        folder_ids: [],
      });
    });

    it('records the sync so the drawer can show it while it indexes', async () => {
      setupOk([{ id: 'src-1', name: 'Handbook' }]);
      const store = await render(drive, vi.fn(), {
        mode: 'sync',
        connectionId: 'conn-drive',
      });
      await click('pick-folder');
      await click('modals.uploadDoc.train');
      const started = (
        store.getState() as {
          connectors: {
            startedSyncs: { id: string; name: string; connectionId: string }[];
          };
        }
      ).connectors.startedSyncs;
      expect(started).toEqual([
        expect.objectContaining({
          id: 'src-1',
          name: 'Handbook',
          connectionId: 'conn-drive',
        }),
      ]);
    });
  });

  it('signs in to an MCP preset with one button and shows its tools', async () => {
    const notion: ConnectorDefinition = {
      ...base,
      key: 'mcp:notion',
      name: 'Notion',
      icon: 'notion',
      auth_kind: 'mcp_oauth',
      credential_fields: [],
      tool_templates: ['mcp_tool'],
      mcp_url: 'https://mcp.notion.com/mcp',
      oauth_scopes: [],
      publisher: 'preset',
    };
    const popup = { closed: false, close: vi.fn(), location: { href: '' } };
    const open = vi.spyOn(window, 'open').mockReturnValue(popup as never);
    mcpApi.testMCPConnection.mockResolvedValue({
      json: async () => ({ requires_oauth: true, task_id: 'task-1' }),
    });
    mcpApi.saveMCPServer.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, id: 'tool-9' }),
    });
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [
        { id: 'conn-9', connector_key: 'mcp:notion', updated_at: '2026-09-28' },
      ],
    });
    service.getConnection.mockResolvedValue({
      success: true,
      connection: { tools: [{ ...TELEGRAM_TOOL, display_name: 'Notion' }] },
    });
    const store = await render(notion);
    // No server URL or auth form: one sign-in button.
    expect(document.body.querySelector('input')).toBeNull();
    await click('settings.connectors.wizard.signIn');
    // The pop-up opens inside the click, then follows the worker.
    expect(open).toHaveBeenCalledWith(
      'about:blank',
      'mcpOAuth',
      expect.any(String),
    );
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.waiting',
    );
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'ev-1',
          type: 'mcp.oauth.awaiting_redirect',
          scope: { kind: 'mcp_oauth', id: 'task-1' },
          payload: { authorization_url: 'https://notion.example/authorize' },
        }),
      );
    });
    expect(popup.location.href).toBe('https://notion.example/authorize');
    await act(async () => {
      store.dispatch(
        sseEventReceived({
          id: 'ev-2',
          type: 'mcp.oauth.completed',
          scope: { kind: 'mcp_oauth', id: 'task-1' },
          payload: { tools: [] },
        }),
      );
    });
    expect(mcpApi.saveMCPServer.mock.calls[0][0]).toMatchObject({
      displayName: 'Notion',
      config: {
        server_url: 'https://mcp.notion.com/mcp',
        auth_type: 'oauth',
        oauth_task_id: 'task-1',
      },
    });
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.doneTitle',
    );
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.toolsHeading:1',
    );
    open.mockRestore();
  });

  it('connects a no-auth MCP preset with one Connect button', async () => {
    const open = vi.spyOn(window, 'open');
    mcpApi.saveMCPServer.mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, id: 'tool-7' }),
    });
    service.listConnections.mockResolvedValue({
      success: true,
      connections: [
        { id: 'conn-7', connector_key: 'mcp:drawio', updated_at: '2026-10-09' },
      ],
    });
    service.getConnection.mockResolvedValue({
      success: true,
      connection: { tools: [{ ...TELEGRAM_TOOL, display_name: 'draw.io' }] },
    });
    await render(drawio);
    expect(document.body.querySelector('input')).toBeNull();
    expect(button('settings.connectors.wizard.signIn')).toBeUndefined();
    await click('settings.connectors.status.connect');
    expect(open).not.toHaveBeenCalled();
    expect(mcpApi.testMCPConnection).not.toHaveBeenCalled();
    const payload = mcpApi.saveMCPServer.mock.calls[0][0];
    expect(payload).toMatchObject({
      displayName: 'draw.io',
      config: { server_url: 'https://mcp.draw.io/mcp', auth_type: 'none' },
    });
    expect(payload.config).not.toHaveProperty('oauth_task_id');
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.doneTitle',
    );
    open.mockRestore();
  });

  it.each(['listConnections', 'getConnection'] as const)(
    'finishes a successful MCP save when %s fails',
    async (failedRequest) => {
      mcpApi.saveMCPServer.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, id: 'tool-7' }),
      });
      service.listConnections.mockResolvedValue({
        success: true,
        connections: [
          { id: 'conn-7', connector_key: drawio.key, updated_at: '2026-10-09' },
        ],
      });
      service[failedRequest].mockRejectedValueOnce(
        new TypeError('Failed to fetch'),
      );
      const onClose = vi.fn();
      await render(drawio, onClose);
      await click('settings.connectors.status.connect');
      expect(title()).toBe('settings.connectors.wizard.doneTitle');
      expect(document.body.textContent).not.toContain('Failed to fetch');
      expect(button('settings.connectors.status.connect')).toBeUndefined();
      expect(mcpApi.saveMCPServer).toHaveBeenCalledTimes(1);
      await click('settings.connectors.wizard.done');
      expect(onClose).toHaveBeenCalledWith(true);
    },
  );

  it('reports a rejected MCP save as a failed connection', async () => {
    mcpApi.saveMCPServer.mockResolvedValue({
      ok: false,
      json: async () => ({ success: false, error: 'Save rejected' }),
    });
    const onClose = vi.fn();
    await render(drawio, onClose);
    await click('settings.connectors.status.connect');
    expect(title()).toBe('settings.connectors.wizard.connectTitle');
    expect(document.body.textContent).toContain('Save rejected');
    await click('cancel');
    expect(onClose).toHaveBeenCalledWith(false);
  });

  describe('GitHub', () => {
    const connectWithToken = async () => {
      service.createConnection.mockResolvedValue({
        success: true,
        connection: { id: 'conn-gh' },
      });
      await connectWithKey('github_pat_abc');
    };

    it('connects with a token when no GitHub App is set up', async () => {
      await render(github);
      // One way in: no method switch, a token field and how to make one,
      // as the field's own hint.
      expect(document.body.querySelector('[role="radiogroup"]')).toBeNull();
      const tokenField = keyField()!;
      expect(
        document.getElementById(tokenField.getAttribute('aria-describedby')!)
          ?.textContent,
      ).toBe('settings.connectors.fieldHints.github_access_token');
      await connectWithToken();
      expect(service.createConnection).toHaveBeenCalledWith(
        {
          connector_key: 'github',
          credentials: { access_token: 'github_pat_abc' },
        },
        null,
      );
      // Tools are asked about, not created on sign-in.
      expect(service.setup).not.toHaveBeenCalled();
      expect(title()).toBe('settings.connectors.wizard.chooseWhatToSetUpFor');
    });

    it('offers Sign in with GitHub first, and a token instead', async () => {
      await render({ ...github, sign_in_methods: ['oauth', 'api_key'] });
      expect(keyField()).toBeNull();
      await click('settings.connectors.wizard.methodToken');
      expect(keyField()).not.toBeNull();
      await click('settings.connectors.wizard.methodOauth');
      await click('settings.connectors.wizard.signIn');
      // The OAuth pop-up (mocked) reported the connection.
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.chooseWhatToSetUp',
      );
    });

    it('says when GitHub refused the token', async () => {
      service.createConnection.mockResolvedValue({
        success: false,
        code: 'invalid_credentials',
      });
      await render(github);
      await connectWithKey('nope');
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.credentialsRejected',
      );
    });

    it('says until when GitHub rate-limited the account', async () => {
      service.createConnection.mockResolvedValue({
        success: false,
        code: 'rate_limited',
        retry_at: '2026-10-26T12:55:00+00:00',
      });
      await render(github);
      await connectWithKey('github_pat_abc');
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.rateLimited',
      );
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.connectFailed',
      );
    });

    it('adds the read-only tools and syncs the picked repository in one step', async () => {
      setupOk(
        [{ id: 'src-1', name: 'octocat/private' }],
        [{ ...TELEGRAM_TOOL, name: 'mcp_tool', display_name: 'GitHub' }],
      );
      await render(github, vi.fn(), { purpose: 'knowledge' });
      await connectWithToken();
      await click('pick-repo');
      await click('modals.uploadDoc.train');
      const [id, body] = service.setup.mock.calls[0];
      expect(id).toBe('conn-gh');
      expect(body).toEqual({
        create_tools: true,
        sync: {
          items: { repo_url: 'octocat/private' },
          frequency: 'weekly',
          name: 'octocat/private',
          config: optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS),
        },
      });
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.doneTitle',
      );
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.toolsHeading:1',
      );
    });

    it('can add only the tools', async () => {
      setupOk();
      await render(github);
      await connectWithToken();
      await click('settings.connectors.wizard.finishSetup');
      expect(service.setup.mock.calls[0][1]).toEqual({ create_tools: true });
    });

    it('can sync without tools', async () => {
      setupOk();
      await render(github, vi.fn(), { purpose: 'knowledge' });
      await connectWithToken();
      const toolSwitch =
        document.body.querySelector<HTMLButtonElement>('[role="switch"]')!;
      expect(toolSwitch.getAttribute('aria-checked')).toBe('true');
      await act(async () => toolSwitch.click());
      await click('pick-repo');
      await click('modals.uploadDoc.train');
      expect(service.setup.mock.calls[0][1].create_tools).toBe(false);
      expect(service.setup.mock.calls[0][1].sync.items).toEqual({
        repo_url: 'octocat/private',
      });
    });

    const writesSwitch = () =>
      document.body.querySelector<HTMLButtonElement>('#tools-github-writes');

    it('offers changes as a second choice, read only by default', async () => {
      setupOk();
      await render({ ...github, writes_opt_in: true, writes_allowed: true });
      await connectWithToken();
      expect(document.body.textContent).toContain(
        'settings.connectors.github.writes',
      );
      expect(writesSwitch()!.getAttribute('aria-checked')).toBe('false');
      await act(async () => writesSwitch()!.click());
      await click('settings.connectors.wizard.finishSetup');
      expect(service.setup.mock.calls[0][1]).toEqual({
        create_tools: true,
        allow_writes: true,
      });
    });

    it('drops the choice with the tools', async () => {
      await render({ ...github, writes_opt_in: true, writes_allowed: true });
      await connectWithToken();
      await act(async () =>
        document.body
          .querySelector<HTMLButtonElement>('#tools-github')!
          .click(),
      );
      expect(writesSwitch()).toBeNull();
    });

    it('hides the choice when an admin turned changes off', async () => {
      await render({ ...github, writes_opt_in: true, writes_allowed: false });
      await connectWithToken();
      expect(writesSwitch()).toBeNull();
      expect(document.body.textContent).not.toContain(
        'settings.connectors.github.writes',
      );
    });
  });

  describe('Linear', () => {
    const linear: ConnectorDefinition = {
      ...base,
      key: 'mcp:linear',
      name: 'Linear',
      icon: 'linear',
      category: 'projects',
      auth_kind: 'mcp_oauth',
      capabilities: ['sync', 'read', 'write'],
      credential_fields: [],
      sync_ingestor: 'linear',
      tool_templates: ['mcp_tool'],
      setup: { tools: 'auto', sync: 'ask' },
      mcp_url: 'https://mcp.linear.app/mcp',
      publisher: 'preset',
    };

    const signIn = async (props = {}, onClose = vi.fn()) => {
      const popup = { closed: false, close: vi.fn(), location: { href: '' } };
      const open = vi.spyOn(window, 'open').mockReturnValue(popup as never);
      mcpApi.testMCPConnection.mockResolvedValue({
        json: async () => ({ requires_oauth: true, task_id: 'task-1' }),
      });
      mcpApi.saveMCPServer.mockResolvedValue({
        ok: true,
        json: async () => ({ success: true, id: 'tool-9' }),
      });
      service.listConnections.mockResolvedValue({
        success: true,
        connections: [
          {
            id: 'conn-lin',
            connector_key: 'mcp:linear',
            updated_at: '2026-09-28',
          },
        ],
      });
      service.getConnection.mockResolvedValue({
        success: true,
        connection: { tools: [{ ...TELEGRAM_TOOL, display_name: 'Linear' }] },
      });
      const store = await render(linear, onClose, props);
      await click('settings.connectors.wizard.signIn');
      await act(async () => {
        store.dispatch(
          sseEventReceived({
            id: 'ev-2',
            type: 'mcp.oauth.completed',
            scope: { kind: 'mcp_oauth', id: 'task-1' },
            payload: { tools: [] },
          }),
        );
      });
      open.mockRestore();
      return store;
    };

    it('signs in once, picks teams to sync, then ends on the summary with its tools', async () => {
      setupOk([{ id: 'src-1', name: 'Linear · Engineering' }]);
      const onClose = vi.fn();
      await signIn({ purpose: 'knowledge' }, onClose);
      // Nothing is set up yet, so the title doesn't say it is connected.
      expect(title()).toBe('settings.connectors.wizard.chooseWhatToSyncFrom');
      expect(document.body.textContent).not.toContain(
        'settings.connectors.wizard.toolsHeading',
      );
      await click('pick-team');
      await click('modals.uploadDoc.train');
      const [id, body] = service.setup.mock.calls[0];
      expect(id).toBe('conn-lin');
      expect(body).toEqual({
        create_tools: false,
        sync: {
          items: {
            teams: [{ id: 't1', key: 'ENG', name: 'Engineering' }],
            projects: [],
            include_comments: true,
            include_documents: false,
          },
          frequency: 'weekly',
          name: 'Linear · Engineering',
          config: optionsToConfig(DEFAULT_RETRIEVAL_OPTIONS),
        },
      });
      // Like every other path: the summary, with the tools from sign-in.
      expect(onClose).not.toHaveBeenCalled();
      expect(title()).toBe('settings.connectors.wizard.doneTitle');
      expect(successAlert()?.textContent).toContain(
        'settings.connectors.wizard.doneCounts',
      );
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.toolsHeading:1',
      );
      await click('settings.connectors.wizard.done');
      expect(onClose).toHaveBeenCalledWith(true);
    });

    it('ends on the summary when nothing is picked and Sync is off', async () => {
      const onClose = vi.fn();
      await signIn({ purpose: 'knowledge' }, onClose);
      // Nothing picked yet: nothing to add.
      expect(button('modals.uploadDoc.train')?.disabled).toBe(true);
      expect(button('settings.connectors.wizard.skip')).toBeUndefined();
      await act(async () => knowledgeSwitch()!.click());
      await click('settings.connectors.wizard.finishSetup');
      expect(service.setup).not.toHaveBeenCalled();
      expect(onClose).not.toHaveBeenCalled();
      expect(title()).toBe('settings.connectors.wizard.doneTitle');
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.toolsHeading:1',
      );
    });

    it('goes straight to the summary after signing in again, with a lone Done', async () => {
      await signIn({ mode: 'reconnect', connectionId: 'conn-lin' });
      expect(document.body.textContent).toContain(
        'settings.connectors.wizard.doneTitle',
      );
      expect(footer()).toEqual(['settings.connectors.wizard.done:default']);
    });

    it('opens on the picker to sync more from the drawer', async () => {
      await render(linear, vi.fn(), {
        mode: 'sync',
        connectionId: 'conn-lin',
      });
      expect(document.body.textContent).toContain('pick-team');
      // Syncing is why it opened: no question about it.
      expect(knowledgeSwitch()).toBeNull();
    });
  });
});
