import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const TOOLS = [
  {
    id: 'tg',
    name: 'telegram',
    displayName: 'Telegram',
    customName: '',
    description: 'Send messages',
    status: true,
    config: {},
    actions: [],
    connection_id: 'conn-1',
  },
  {
    id: 'api',
    name: 'api_tool',
    displayName: 'API Tool',
    customName: 'My API',
    description: 'Calls an API',
    status: true,
    config: {},
    actions: [],
    connection_id: null,
  },
];

vi.mock('../api/services/userService', () => ({
  default: {
    getUserTools: vi.fn(async () => ({ json: async () => ({ tools: TOOLS }) })),
    getMCPAuthStatus: vi.fn(async () => ({
      json: async () => ({ statuses: {} }),
    })),
    getAvailableTools: vi.fn(async () => ({
      json: async () => ({ data: [] }),
    })),
  },
}));
vi.mock('../api/services/connectorsService', () => ({
  default: {
    getCatalog: vi.fn(async () => ({ success: true, connectors: [] })),
    listConnections: vi.fn(async () => ({
      success: true,
      connections: [
        {
          id: 'conn-1',
          connector_key: 'telegram',
          name: 'Telegram',
          icon: 'tool_telegram',
          status: 'connected',
          account_label: '…abcd',
        },
      ],
    })),
  },
}));

import connectorsReducer from '../connectors/connectorsSlice';
import notificationsReducer from '../notifications/notificationsSlice';
import Tools from './Tools';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname + location.search}</div>;
}

describe('Tools page', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async () => {
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        notifications: notificationsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/settings/tools']}>
            <Routes>
              <Route path="/settings/tools" element={<Tools />} />
              <Route path="/settings/connectors" element={<Where />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });
  };

  const openMenu = async (index: number) => {
    const triggers = container.querySelectorAll<HTMLButtonElement>(
      '[aria-label="settings.tools.settingsIconAlt"]',
    );
    await act(async () => {
      triggers[index].dispatchEvent(
        new PointerEvent('pointerdown', { bubbles: true, button: 0 }),
      );
    });
  };

  const menuItem = (text: string) =>
    Array.from(
      document.body.querySelectorAll<HTMLElement>('[role="menuitem"]'),
    ).find((item) => item.textContent?.includes(text));

  it('sends a connected tool to its connector page to manage it', async () => {
    await render();
    await openMenu(0);
    expect(menuItem('settings.tools.edit')).toBeUndefined();
    await act(async () =>
      menuItem('settings.connectors.manageConnection')!.click(),
    );
    expect(
      document.body.querySelector('[data-testid="where"]')?.textContent,
    ).toBe('/settings/connectors?connector=telegram');
  });

  it('keeps Edit for a tool that is not from a connection', async () => {
    await render();
    await openMenu(1);
    expect(menuItem('settings.tools.edit')).toBeDefined();
    expect(menuItem('settings.connectors.manageConnection')).toBeUndefined();
  });
});
