import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) =>
      opts?.name ? `${key}:${opts.name}` : key,
  }),
}));

const launch = vi.hoisted(() => vi.fn());
vi.mock('./useConnectorLauncher', () => ({
  default: () => ({ launch, modals: null }),
}));

import connectorsReducer from './connectorsSlice';
import SignInAgainNotice, { useSignInAgain } from './SignInAgainNotice';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const LINEAR = {
  key: 'mcp:linear',
  name: 'Linear',
  auth_kind: 'mcp_oauth',
  mcp_url: 'https://mcp.linear.app/mcp',
  available: true,
};
const CUSTOM = { key: 'custom_mcp', name: 'MCP server', auth_kind: 'mcp' };

function Where() {
  return (
    <div data-testid="where">
      {useLocation().pathname + useLocation().search}
    </div>
  );
}

function Harness({
  connectorKey,
  mcpToolId,
}: {
  connectorKey: string;
  mcpToolId?: string;
}) {
  const { reconnect, modals } = useSignInAgain();
  return (
    <>
      <SignInAgainNotice
        connections={[
          { id: 'conn-2', connector_key: connectorKey, name: 'Linear' },
        ]}
        onReconnect={(connection) => reconnect(connection, mcpToolId)}
      />
      {modals}
    </>
  );
}

describe('SignInAgainNotice', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    launch.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const render = async (connectorKey: string, mcpToolId?: string) => {
    const store = configureStore({
      reducer: { connectors: connectorsReducer },
      preloadedState: {
        connectors: {
          enabled: true,
          loading: false,
          loaded: true,
          failed: false,
          catalog: [LINEAR, CUSTOM],
          connections: [],
        },
      },
    } as Parameters<typeof configureStore>[0]);
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter initialEntries={['/']}>
            <Routes>
              <Route
                path="/"
                element={
                  <Harness connectorKey={connectorKey} mcpToolId={mcpToolId} />
                }
              />
              <Route path="/settings/connectors" element={<Where />} />
            </Routes>
          </MemoryRouter>
        </Provider>,
      );
    });
  };

  const reconnectButton = () =>
    Array.from(container.querySelectorAll('button')).find(
      (b) => b.textContent === 'settings.connectors.status.reconnect',
    )!;

  it('names the connection that needs signing in again', async () => {
    await render('mcp:linear');
    expect(container.textContent).toContain(
      'settings.connectors.health.pickerNotice:Linear',
    );
  });

  it('reconnects a service in place, keeping its MCP tool', async () => {
    await render('mcp:linear', 'tool-lin');
    await act(async () => reconnectButton().click());
    expect(launch).toHaveBeenCalledWith(LINEAR, {
      mode: 'reconnect',
      connectionId: 'conn-2',
      mcpServer: { id: 'tool-lin' },
    });
  });

  it('opens the connector page on that account when the sign-in needs its form', async () => {
    await render('custom_mcp');
    await act(async () => reconnectButton().click());
    expect(launch).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="where"]')?.textContent).toBe(
      '/settings/connectors?connector=custom_mcp&connection=conn-2',
    );
  });

  it('renders nothing when every connection works', async () => {
    const store = configureStore({
      reducer: { connectors: connectorsReducer },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <SignInAgainNotice connections={[]} onReconnect={vi.fn()} />
        </Provider>,
      );
    });
    expect(container.innerHTML).toBe('');
  });
});
