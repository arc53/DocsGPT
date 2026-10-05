import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: { name?: string; owner?: string }) =>
      [key, opts?.name, opts?.owner].filter(Boolean).join(':'),
  }),
}));

vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: vi.fn().mockResolvedValue({ success: true, connectors: [] }),
    listConnections: vi
      .fn()
      .mockResolvedValue({ success: true, connections: [] }),
  },
}));

const launch = vi.fn();
const launcherOptions = vi.hoisted(() => ({
  current: {} as { onConnected?: () => void },
}));
vi.mock('../connectors/useConnectorLauncher', () => ({
  default: (options: { onConnected?: () => void } = {}) => {
    launcherOptions.current = options;
    return { launch, modals: null };
  },
}));

import connectorsReducer from '../connectors/connectorsSlice';
import ConnectToolCallBar from './ConnectToolCallBar';
import type { ToolCallsType } from './types';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const call = (status: string): ToolCallsType => ({
  tool_name: 'mcp_tool',
  action_name: 'search_pages',
  call_id: 'call-1',
  arguments: {},
  status: 'awaiting_approval',
  connection_required: {
    connector_key: 'mcp:notion',
    connector_name: 'Notion',
    status,
  },
});

describe('ConnectToolCallBar', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (
    toolCall: ToolCallsType,
    onToolAction = vi.fn(),
    connectors?: Record<string, unknown>,
  ) => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
      preloadedState: connectors
        ? {
            connectors: {
              enabled: true,
              loading: false,
              loaded: true,
              failed: false,
              catalog: [],
              connections: [],
              ...connectors,
            },
            preference: { token: null },
          }
        : undefined,
    } as Parameters<typeof configureStore>[0]);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/c/1']}>
            <Routes>
              <Route
                path="/c/1"
                element={
                  <ConnectToolCallBar
                    toolCall={toolCall}
                    onToolAction={onToolAction}
                  />
                }
              />
              <Route path="/settings/connectors" element={<div>DRAWER</div>} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    return onToolAction;
  };

  const button = (text: string) =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === text,
    )!;

  it('a cancelled connect does not offer Continue', async () => {
    await render(call('missing'), vi.fn(), { catalog: [] });
    // The launcher reports every close, cancelled or not.
    await act(async () => launcherOptions.current.onConnected?.());
    expect(button('conversation.toolApproval.continue')).toBeUndefined();
  });

  it('offers Continue once an account for the service is connected', async () => {
    await render(call('missing'), vi.fn(), {
      connections: [
        { id: 'c9', connector_key: 'mcp:notion', status: 'connected' },
      ],
    });
    expect(button('conversation.toolApproval.continue')).toBeDefined();
  });

  it('names the service it needs', async () => {
    await render(call('missing'));
    expect(container.textContent).toContain(
      'conversation.toolApproval.connectTitle:Notion',
    );
    expect(button('conversation.toolApproval.connect:Notion')).toBeDefined();
  });

  it('skipping denies the pending call', async () => {
    const onToolAction = await render(call('missing'));
    await act(async () => button('conversation.toolApproval.skip').click());
    expect(onToolAction).toHaveBeenCalledWith('call-1', 'denied');
  });

  const TELEGRAM = {
    key: 'telegram',
    name: 'Telegram',
    icon: 'tool_telegram',
    auth_kind: 'api_key',
  };
  const ownCall = (status: string): ToolCallsType => ({
    ...call(status),
    connection_required: {
      connector_key: 'telegram',
      connector_name: 'Telegram',
      status,
      connection_id: 'conn-1',
      owner_account: false,
    },
  });

  it('reconnects your own account right here', async () => {
    launch.mockClear();
    await render(ownCall('reconnect_needed'), vi.fn(), {
      catalog: [TELEGRAM],
      connections: [{ id: 'conn-1', status: 'reconnect_needed' }],
    });
    await act(async () =>
      button('settings.connectors.status.reconnect').click(),
    );
    expect(launch).toHaveBeenCalledWith(TELEGRAM, {
      mode: 'reconnect',
      connectionId: 'conn-1',
    });
    expect(document.body.textContent).not.toContain('DRAWER');
  });

  it('offers Continue once the connection works again', async () => {
    await render(ownCall('reconnect_needed'), vi.fn(), {
      catalog: [TELEGRAM],
      connections: [{ id: 'conn-1', status: 'connected' }],
    });
    expect(button('conversation.toolApproval.continue')).toBeDefined();
  });

  it('an account that needs signing in again is healed from its drawer', async () => {
    await render(call('reconnect_needed'));
    await act(async () =>
      button('settings.connectors.status.reconnect').click(),
    );
    expect(document.body.textContent).toContain('DRAWER');
  });

  it('asks you to sign in again, not to connect, for a reconnect', async () => {
    await render(ownCall('reconnect_needed'), vi.fn(), {
      catalog: [TELEGRAM],
      connections: [{ id: 'conn-1', status: 'reconnect_needed' }],
    });
    expect(container.textContent).toContain(
      'settings.connectors.health.pickerNotice:Telegram',
    );
    expect(container.textContent).not.toContain(
      'conversation.toolApproval.connectTitle',
    );
    expect(button('settings.connectors.status.reconnect')).toBeDefined();
    expect(
      button('conversation.toolApproval.connect:Telegram'),
    ).toBeUndefined();
  });

  it('names the call and its state in the shared card header', async () => {
    await render(call('missing'));
    expect(container.textContent).toContain(
      'conversation.toolApproval.title:Notion',
    );
    expect(container.textContent).toContain(
      'conversation.toolApproval.state.notConnected',
    );
  });

  it('says the service is connected once it is', async () => {
    await render(call('missing'), vi.fn(), {
      connections: [
        { id: 'c9', connector_key: 'mcp:notion', status: 'connected' },
      ],
    });
    expect(container.textContent).toContain(
      'conversation.toolApproval.connectedTitle:Notion',
    );
    expect(container.textContent).toContain(
      'settings.connectors.status.connected',
    );
  });

  it('never says "your this service account" without a name', async () => {
    await render({
      ...call('missing'),
      connection_required: {
        connector_key: null,
        connector_name: null,
        status: 'missing',
      },
    });
    expect(container.textContent).toContain(
      'conversation.toolApproval.connectTitleGeneric',
    );
    expect(button('settings.connectors.status.connect')).toBeDefined();
  });

  const ownerCall = (owner_name?: string): ToolCallsType => ({
    ...call('reconnect_needed'),
    tool_name: 'github',
    action_name: 'create_issue',
    connection_required: {
      connector_key: 'github',
      connector_name: 'GitHub',
      status: 'reconnect_needed',
      owner_account: true,
      ...(owner_name ? { owner_name } : {}),
    },
  });

  it("asks for the owner on the owner's broken account, Skip only", async () => {
    await render(ownerCall('lena@example.com'), vi.fn(), {
      // Even with an account of your own, the call runs on the owner's.
      connections: [{ id: 'c9', connector_key: 'github', status: 'connected' }],
    });
    expect(container.textContent).toContain(
      'conversation.toolApproval.ownerReconnect:GitHub:lena@example.com',
    );
    const labels = Array.from(container.querySelectorAll('button')).map(
      (b) => b.textContent,
    );
    expect(labels).toEqual(['conversation.toolApproval.skip']);
  });

  it('falls back to generic owner copy without the owner name', async () => {
    await render(ownerCall());
    expect(container.textContent).toContain(
      'conversation.toolApproval.ownerReconnectGeneric',
    );
    expect(button('conversation.toolApproval.skip')).toBeDefined();
    expect(button('settings.connectors.status.reconnect')).toBeUndefined();
  });
});
