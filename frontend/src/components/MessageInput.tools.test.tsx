import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';

import type { MultiSelectPopoverItem } from './MultiSelectPopover';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));

const mocks = vi.hoisted(() => ({
  tools: [] as unknown[],
  catalog: [] as unknown[],
  connections: [] as unknown[],
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, tools: mocks.tools }),
      }),
  },
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: () =>
      Promise.resolve({ success: true, connectors: mocks.catalog }),
    listConnections: () =>
      Promise.resolve({ success: true, connections: mocks.connections }),
  },
}));

// The Tools picker renders each item's group; a button opens it.
vi.mock('./message-input', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./message-input')>()),
  ToolsTrigger: ({
    items,
    onOpenChange,
  }: {
    items: MultiSelectPopoverItem[];
    onOpenChange: (open: boolean) => void;
  }) => (
    <div>
      <button
        type="button"
        data-testid="open-tools"
        onClick={() => onOpenChange(true)}
      />
      {items.map((item) => (
        <div key={item.id} data-testid="tool-item" data-group={item.group}>
          {item.label}
          {item.descriptionNode && (
            <div data-testid="tool-note">{item.descriptionNode}</div>
          )}
        </div>
      ))}
    </div>
  ),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import notificationsReducer from '../notifications/notificationsSlice';
import { prefSlice } from '../preferences/preferenceSlice';
import uploadReducer from '../upload/uploadSlice';
import MessageInput from './MessageInput';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const makeStore = () =>
  configureStore({
    reducer: {
      preference: prefSlice.reducer,
      upload: uploadReducer,
      notifications: notificationsReducer,
      connectors: connectorsReducer,
    },
  });

describe('MessageInput tools picker', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    localStorage.clear();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const openPicker = async () => {
    await act(async () => {
      root.render(
        <Provider store={makeStore()}>
          <MessageInput
            onSubmit={() => undefined}
            loading={false}
            showSourceButton={false}
            showToolButton
            autoFocus={false}
          />
        </Provider>,
      );
    });
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-testid="open-tools"]')!
        .click();
    });
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
  };

  const groups = () =>
    Object.fromEntries(
      Array.from(
        container.querySelectorAll<HTMLElement>('[data-testid="tool-item"]'),
      ).map((item) => [item.firstChild?.textContent, item.dataset.group]),
    );

  // A teammate's connection is never in the caller's list; the tool still
  // sits under its service rather than with the built-in or custom tools.
  it("groups a teammate's connected tool under its service", async () => {
    mocks.catalog = [
      {
        key: 'linear',
        name: 'Linear',
        icon: 'linear',
        publisher: 'preset',
        tool_templates: ['mcp_tool'],
        mcp_url: 'https://mcp.linear.app/mcp',
      },
    ];
    mocks.tools = [
      {
        id: 'mem',
        name: 'memory',
        displayName: 'Memory',
        default: true,
        status: true,
        config: {},
      },
      {
        id: 'lin',
        name: 'mcp_tool',
        displayName: 'Linear',
        customName: 'Team Linear',
        connection_id: 'owner-conn',
        status: false,
        in_chat: false,
        access: 'viewer',
        allowed_actions: ['use', 'use_in_own'],
        config: { server_url: 'https://mcp.linear.app/mcp' },
      },
    ];
    await openPicker();
    expect(groups()).toEqual({
      Memory: 'settings.tools.groupBuiltIn',
      'Team Linear': 'Linear',
    });
  });

  it('marks a tool whose connection needs signing in with the Reconnect badge', async () => {
    mocks.catalog = [];
    mocks.connections = [
      {
        id: 'conn-1',
        connector_key: 'telegram',
        name: 'Telegram',
        icon: 'tool_telegram',
        status: 'reconnect_needed',
      },
    ];
    mocks.tools = [
      {
        id: 'tg',
        name: 'telegram',
        displayName: 'Telegram',
        connection_id: 'conn-1',
        status: true,
        config: {},
      },
    ];
    await openPicker();
    const note = container.querySelector('[data-testid="tool-note"]')!;
    const badge = note.querySelector('[data-slot="badge"]')!;
    expect(badge.textContent).toBe('settings.connectors.status.reconnect');
    expect(badge.getAttribute('data-variant')).toBe('warning');
  });
});
