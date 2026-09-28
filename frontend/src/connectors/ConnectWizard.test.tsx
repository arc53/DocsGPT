import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

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
}));
vi.mock('../api/services/connectorsService', () => ({ default: service }));

// The OAuth popup is covered by ConnectorAuth's own tests; here it only has
// to report a finished sign-in.
vi.mock('../components/ConnectorAuth', () => ({
  default: ({
    onSuccess,
    label,
  }: {
    onSuccess: (data: { connection_id: string; user_email: string }) => void;
    label: string;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSuccess({ connection_id: 'conn-drive', user_email: 'a@example.com' })
      }
    >
      {label}
    </button>
  ),
}));
vi.mock('../components/FilePicker', () => ({
  FilePicker: ({
    onSelectionChange,
    onFirstPickName,
  }: {
    onSelectionChange: (files: string[], folders?: string[]) => void;
    onFirstPickName?: (name: string) => void;
  }) => (
    <button
      type="button"
      onClick={() => {
        onFirstPickName?.('Handbook');
        onSelectionChange([], ['folder-1']);
      }}
    >
      pick-folder
    </button>
  ),
}));

import connectorsReducer from './connectorsSlice';
import ConnectWizard from './ConnectWizard';
import type { ConnectorDefinition } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (connector: ConnectorDefinition, onClose = vi.fn()) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null, selectedDocs: [] }) => state,
        conversation: (state = {}) => state,
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
                  <ConnectWizard connector={connector} onClose={onClose} />
                }
              />
              <Route path="/c/new" element={<div>NEW_CHAT</div>} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const click = async (text: string) => {
    const button = Array.from(
      document.body.querySelectorAll<HTMLButtonElement>('button'),
    ).find((b) => b.textContent?.trim() === text);
    expect(button, `button ${text}`).toBeDefined();
    await act(async () => button!.click());
  };

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

  it('connects an API-key service and creates its tools with no further questions', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    service.setup.mockResolvedValue({
      success: true,
      tools: [TELEGRAM_TOOL],
      sources: [],
    });
    await render(base);
    const input = document.body.querySelector<HTMLInputElement>(
      'input[type="password"]',
    )!;
    await typeInto(input, '123:abc');
    await click('settings.connectors.status.connect');
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
  });

  it('shows the default-key refusal in the form', async () => {
    service.createConnection.mockResolvedValue({
      success: false,
      code: 'encryption_key_default',
    });
    await render(base);
    await typeInto(
      document.body.querySelector<HTMLInputElement>('input[type="password"]')!,
      'x',
    );
    await click('settings.connectors.status.connect');
    expect(document.body.textContent).toContain(
      'settings.connectors.error.defaultKey',
    );
  });

  it('lets a content service skip choosing what to sync', async () => {
    await render(drive);
    await click('settings.connectors.wizard.signIn');
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.chooseWhatToSync',
    );
    await click('settings.connectors.wizard.skip');
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.doneTitle',
    );
    expect(service.setup).not.toHaveBeenCalled();
  });

  it('syncs the picked folder named after it', async () => {
    service.setup.mockResolvedValue({
      success: true,
      tools: [],
      sources: [{ id: 'src-1', name: 'Handbook' }],
    });
    await render(drive);
    await click('settings.connectors.wizard.signIn');
    await click('pick-folder');
    await click('modals.uploadDoc.train');
    const [id, body, , key] = service.setup.mock.calls[0];
    expect(id).toBe('conn-drive');
    expect(body.sync).toEqual({
      items: { file_ids: [], folder_ids: ['folder-1'] },
      frequency: 'weekly',
      name: 'Handbook',
    });
    expect(typeof key).toBe('string');
    expect(document.body.textContent).toContain(
      'settings.connectors.wizard.doneSummary',
    );
  });

  it('opens a new chat from Try it in chat', async () => {
    service.createConnection.mockResolvedValue({
      success: true,
      connection: { id: 'conn-1' },
    });
    service.setup.mockResolvedValue({ success: true, tools: [], sources: [] });
    const onClose = vi.fn();
    await render(base, onClose);
    await typeInto(
      document.body.querySelector<HTMLInputElement>('input[type="password"]')!,
      't',
    );
    await click('settings.connectors.status.connect');
    await click('settings.connectors.wizard.tryInChat');
    expect(onClose).toHaveBeenCalled();
    expect(document.body.textContent).toContain('NEW_CHAT');
  });
});
