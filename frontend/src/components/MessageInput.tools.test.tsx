import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

import type { MultiSelectPopoverItem } from './MultiSelectPopover';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock('../upload/Upload', () => ({ default: () => null }));
const addTool = vi.hoisted(() => ({
  props: null as null | { onToolsCreated: (ids: string[]) => void },
}));
vi.mock('../modals/AddToolModal', () => ({
  default: (props: { onToolsCreated: (ids: string[]) => void }) => {
    addTool.props = props;
    return null;
  },
}));
vi.mock('../connectors/SignInAgainNotice', () => ({
  default: () => null,
  useSignInAgain: () => ({ reconnect: vi.fn(), modals: null }),
}));

const mocks = vi.hoisted(() => ({
  tools: [] as unknown[],
  // Responses handed out in request order, when a test controls them.
  queued: [] as Promise<unknown>[],
  catalog: [] as unknown[],
  connections: [] as unknown[],
  updateStatus: vi.fn(() => Promise.resolve({ ok: true })),
  devices: vi.fn(() =>
    Promise.resolve({
      devices: [{ id: 'd1', last_seen_at: new Date().toISOString() }],
    }),
  ),
}));

vi.mock('../api/services/devicesService', () => ({
  default: { list: () => mocks.devices() },
}));

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: () =>
      mocks.queued.shift() ??
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ success: true, tools: mocks.tools }),
      }),
    updateToolStatus: () => mocks.updateStatus(),
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
    onToggle,
    filters,
  }: {
    items: MultiSelectPopoverItem[];
    onOpenChange: (open: boolean) => void;
    onToggle: (id: string) => void;
    filters?: React.ReactNode;
  }) => (
    <div>
      <div data-testid="tool-filters">{filters}</div>
      <button
        type="button"
        data-testid="open-tools"
        onClick={() => onOpenChange(true)}
      />
      {items.map((item) => (
        <div
          key={item.id}
          data-testid="tool-item"
          data-group={item.group}
          data-description={item.description}
        >
          {item.label}
          {item.descriptionNode && (
            <div data-testid="tool-note">{item.descriptionNode}</div>
          )}
          <button
            type="button"
            data-testid="toggle-tool"
            onClick={() => onToggle(item.id)}
          />
        </div>
      ))}
    </div>
  ),
}));

import connectorsReducer from '../connectors/connectorsSlice';
import chatToolsReducer, {
  loadChatTools,
  setChatToolInChat,
} from '../conversation/chatToolsSlice';
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
      chatTools: chatToolsReducer,
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
        <MemoryRouter>
          <Provider store={makeStore()}>
            <MessageInput
              onSubmit={() => undefined}
              loading={false}
              showSourceButton={false}
              showToolButton
              autoFocus={false}
            />
          </Provider>
        </MemoryRouter>,
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

  // A new tool is created on, so it is in the chat once the list refreshes.
  it('reloads its tools after Add tool made some', async () => {
    mocks.tools = [];
    await openPicker();
    expect(
      container.querySelectorAll('[data-testid="tool-item"]'),
    ).toHaveLength(0);
    mocks.tools = [
      {
        id: 'fresh',
        name: 'memory',
        displayName: 'Fresh',
        default: true,
        status: true,
        config: {},
      },
    ];
    await act(async () => addTool.props!.onToolsCreated(['fresh']));
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
    expect(Object.keys(groups())).toEqual(['Fresh']);
    mocks.tools = [];
  });

  // The list loads on mount and again when the picker opens; an older answer
  // arriving last must not replace the newer one.
  it('keeps the latest tool list when an older request answers last', async () => {
    const tool = (id: string) => ({
      id,
      name: 'memory',
      displayName: id,
      default: true,
      status: true,
      config: {},
    });
    const deferred = () => {
      let resolve: (tools: unknown[]) => void = () => {};
      const promise = new Promise<unknown>((r) => {
        resolve = (tools) =>
          r({
            ok: true,
            json: () => Promise.resolve({ success: true, tools }),
          });
      });
      return { promise, resolve };
    };
    const onMount = deferred();
    const onOpen = deferred();
    mocks.queued = [onMount.promise, onOpen.promise];
    await openPicker();
    await act(async () => onOpen.resolve([tool('Newer')]));
    await act(async () => onMount.resolve([tool('Older')]));
    for (let i = 0; i < 4; i += 1) {
      await act(async () => {
        await Promise.resolve();
      });
    }
    expect(Object.keys(groups())).toEqual(['Newer']);
    mocks.queued = [];
  });

  // A chat switch remounts the composer while the old one's load is still
  // out; that answer must not overwrite the list the new composer loaded
  // and the user has since toggled.
  it("ignores an unmounted composer's late tool list", async () => {
    const tool = (id: string, status: boolean) => ({
      id,
      name: 'memory',
      displayName: id,
      status,
      config: {},
    });
    const deferred = () => {
      let resolve: (tools: unknown[]) => void = () => {};
      const promise = new Promise<unknown>((r) => {
        resolve = (tools) =>
          r({
            ok: true,
            json: () => Promise.resolve({ success: true, tools }),
          });
      });
      return { promise, resolve };
    };
    const flush = async () => {
      for (let i = 0; i < 4; i += 1) {
        await act(async () => {
          await Promise.resolve();
        });
      }
    };
    const store = makeStore();
    const composer = (key: string) => (
      <MemoryRouter>
        <Provider store={store}>
          <MessageInput
            key={key}
            onSubmit={() => undefined}
            loading={false}
            showSourceButton={false}
            showToolButton
            autoFocus={false}
          />
        </Provider>
      </MemoryRouter>
    );
    const fromA = deferred();
    const fromB = deferred();
    mocks.queued = [fromA.promise, fromB.promise];
    await act(async () => root.render(composer('chat-a')));
    await act(async () => root.render(composer('chat-b')));
    await act(async () => fromB.resolve([tool('notes', false)]));
    await flush();
    await act(async () => {
      store.dispatch(
        setChatToolInChat({ id: 'notes', value: true, owner: true }),
      );
    });
    await act(async () => fromA.resolve([tool('notes', false)]));
    await flush();
    expect(store.getState().chatTools.tools).toEqual([
      expect.objectContaining({ id: 'notes', status: true, in_chat: true }),
    ]);
    expect(store.getState().chatTools.loading).toBe(false);
    mocks.queued = [];
  });

  // Closing and reopening the picker reloads it before the switch has
  // reached the server; the tick holds until the update answers.
  describe('a toggled tool', () => {
    const notes = (status: boolean) => ({
      id: 'notes',
      name: 'memory',
      displayName: 'Notes',
      status,
      config: {},
    });
    const flush = async () => {
      for (let i = 0; i < 4; i += 1) {
        await act(async () => {
          await Promise.resolve();
        });
      }
    };
    const toggleWithUpdateOut = async () => {
      let answer: (outcome: Promise<{ ok: boolean }>) => void = () => {};
      mocks.updateStatus.mockReturnValueOnce(
        new Promise<{ ok: boolean }>((resolve) => {
          answer = resolve;
        }),
      );
      mocks.tools = [notes(false)];
      const store = makeStore();
      await act(async () => {
        root.render(
          <MemoryRouter>
            <Provider store={store}>
              <MessageInput
                onSubmit={() => undefined}
                loading={false}
                showSourceButton={false}
                showToolButton
                autoFocus={false}
              />
            </Provider>
          </MemoryRouter>,
        );
      });
      await flush();
      await act(async () => {
        container
          .querySelector<HTMLButtonElement>('[data-testid="toggle-tool"]')!
          .click();
      });
      // The reload reads the list before the switch reached the server.
      await act(async () => {
        await store.dispatch(loadChatTools({ token: null }));
      });
      expect(store.getState().chatTools.tools[0]).toMatchObject({
        status: true,
        in_chat: true,
      });
      return { store, answer };
    };

    afterEach(() => {
      mocks.tools = [];
    });

    it('holds until its update answers, then takes the reloaded list', async () => {
      const { store, answer } = await toggleWithUpdateOut();
      await act(async () => answer(Promise.resolve({ ok: true })));
      await flush();
      expect(store.getState().chatTools.pendingToggles).toEqual({});
      mocks.tools = [notes(false)];
      await act(async () => {
        await store.dispatch(loadChatTools({ token: null }));
      });
      expect(store.getState().chatTools.tools[0]).toMatchObject({
        status: false,
      });
    });

    it.each([
      ['refused', () => Promise.resolve({ ok: false })],
      ['unreachable', () => Promise.reject<{ ok: boolean }>(new Error('down'))],
    ])(
      'unticks and stops holding when the update is %s',
      async (_, outcome) => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        const { store, answer } = await toggleWithUpdateOut();
        await act(async () => answer(outcome()));
        await flush();
        expect(store.getState().chatTools.tools[0]).toMatchObject({
          status: false,
          in_chat: false,
        });
        expect(store.getState().chatTools.pendingToggles).toEqual({});
        vi.mocked(console.error).mockRestore();
      },
    );
  });

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
      Memory: 'included',
      'Team Linear': 'service:Linear',
    });
  });

  // The same groups as the agent builder and the Tools page.
  it('groups included, added, each service, then custom', async () => {
    mocks.catalog = [];
    mocks.connections = [];
    mocks.tools = [
      {
        id: 'api',
        name: 'api_tool',
        displayName: 'API',
        customName: 'Rates API',
        status: true,
        config: {},
      },
      {
        id: 'mine',
        name: 'memory',
        displayName: 'Notes memory',
        description: 'Remembers account context',
        status: true,
        config: {},
      },
      {
        id: 'mem',
        name: 'memory',
        displayName: 'Memory',
        description: 'Stores and retrieves information',
        default: true,
        status: true,
        config: {},
      },
    ];
    await openPicker();
    expect(groups()).toEqual({
      Memory: 'included',
      'Notes memory': 'added',
      'Rates API': 'custom',
    });
    // Each row's line tells copies of one tool apart.
    const line = (label: string) =>
      Array.from(
        container.querySelectorAll<HTMLElement>('[data-testid="tool-item"]'),
      ).find((item) => item.firstChild?.textContent === label)?.dataset
        .description;
    expect(line('Memory')).toBe('Stores and retrieves information');
    expect(line('Notes memory')).toBe('Remembers account context');
  });

  it('draws the kind track past 10 tools and narrows the rows to a kind', async () => {
    mocks.catalog = [];
    mocks.connections = [];
    mocks.tools = [
      ...Array.from({ length: 9 }, (_, i) => ({
        id: `added-${i}`,
        name: 'memory',
        displayName: `Notes ${i}`,
        status: true,
        config: {},
      })),
      {
        id: 'web',
        name: 'read_webpage',
        displayName: 'Read webpage',
        default: true,
        status: true,
        config: {},
      },
      {
        id: 'api',
        name: 'api_tool',
        displayName: 'API',
        status: true,
        config: {},
      },
    ];
    await openPicker();
    const filters = container.querySelector('[data-testid="tool-filters"]')!;
    const track = filters.querySelector('[data-slot="toggle-group"]');
    expect(track?.getAttribute('aria-label')).toBe(
      'settings.tools.kindFilterLabel',
    );
    const custom = Array.from(
      filters.querySelectorAll<HTMLButtonElement>(
        '[data-slot="toggle-group-item"]',
      ),
    ).find((item) =>
      item.textContent?.startsWith('agents.form.toolsPopup.groupCustom'),
    )!;
    await act(async () => custom.click());
    expect(
      Array.from(container.querySelectorAll('[data-testid="tool-item"]')).map(
        (item) => item.firstChild?.textContent,
      ),
    ).toEqual(['API']);
  });

  it('draws no kind track while the tools fit on one screen', async () => {
    mocks.catalog = [];
    mocks.connections = [];
    mocks.tools = [
      { id: 'a', name: 'memory', displayName: 'A', status: true, config: {} },
      { id: 'b', name: 'api_tool', displayName: 'B', status: true, config: {} },
    ];
    await openPicker();
    expect(
      container.querySelector('[data-testid="tool-filters"]')!.innerHTML,
    ).toBe('');
  });

  // Only the agent builder loaded device status before; the chat picker now
  // asks for it when it opens with a remote device in the list.
  it('marks a remote device online once the picker opens', async () => {
    mocks.devices.mockClear();
    mocks.catalog = [];
    mocks.connections = [];
    mocks.tools = [
      {
        id: 'dev',
        name: 'remote_device',
        displayName: 'Laptop',
        description: 'Spreadsheet clean-up',
        status: true,
        config: { device_id: 'd1' },
      },
    ];
    await openPicker();
    expect(mocks.devices).toHaveBeenCalled();
    const badge = container.querySelector(
      '[data-testid="tool-note"] [data-slot="badge"]',
    )!;
    expect(badge.textContent).toBe('settings.devices.online');
    expect(badge.getAttribute('data-variant')).toBe('success');
  });

  it('asks for devices only when a remote device is listed', async () => {
    mocks.devices.mockClear();
    mocks.tools = [
      {
        id: 'mem',
        name: 'memory',
        displayName: 'Memory',
        default: true,
        status: true,
        config: {},
      },
    ];
    await openPicker();
    expect(mocks.devices).not.toHaveBeenCalled();
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
