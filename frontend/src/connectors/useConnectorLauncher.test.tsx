import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

// The wizard is tested on its own; here only what it is opened with matters.
vi.mock('./ConnectWizard', () => ({
  default: ({
    mode,
    connectionId,
    purpose,
  }: {
    mode: string;
    connectionId?: string;
    purpose?: string;
  }) => (
    <div data-testid="wizard" data-purpose={purpose ?? ''}>
      {`${mode}:${connectionId ?? ''}`}
    </div>
  ),
}));
vi.mock('../modals/MCPServerModal', () => ({ default: () => null }));

import connectorsReducer from './connectorsSlice';
import type { ConnectorDefinition } from './types';
import useConnectorLauncher, {
  type LaunchOptions,
} from './useConnectorLauncher';

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const LINEAR = {
  key: 'mcp:linear',
  name: 'Linear',
  auth_kind: 'mcp_oauth',
  mcp_url: 'https://mcp.linear.app/mcp',
  sync_ingestor: 'linear',
} as unknown as ConnectorDefinition;

const DRIVE = {
  key: 'google_drive',
  name: 'Google Drive',
  auth_kind: 'oauth',
  mcp_url: null,
  sync_ingestor: 'google_drive',
} as unknown as ConnectorDefinition;

let launchRef: ((c: ConnectorDefinition, o?: LaunchOptions) => void) | null =
  null;

function Harness() {
  const { launch, modals } = useConnectorLauncher();
  launchRef = launch;
  return <>{modals}</>;
}

describe('useConnectorLauncher', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    const store = configureStore({
      reducer: {
        connectors: connectorsReducer,
        preference: (state = { token: null }) => state,
      },
    });
    await act(async () => {
      root.render(
        <Provider store={store}>
          <MemoryRouter>
            <Harness />
          </MemoryRouter>
        </Provider>,
      );
    });
  });

  afterEach(async () => {
    await act(async () => root.unmount());
    container.remove();
  });

  const wizard = () =>
    container.querySelector('[data-testid="wizard"]')?.textContent;

  it('opens an MCP preset that syncs straight at picking what to sync', async () => {
    await act(async () =>
      launchRef!(LINEAR, { mode: 'sync', connectionId: 'c1' }),
    );
    expect(wizard()).toBe('sync:c1');
  });

  it('opens an MCP preset at signing in to connect or reconnect', async () => {
    await act(async () => launchRef!(LINEAR));
    expect(wizard()).toBe('connect:');
    await act(async () =>
      launchRef!(LINEAR, { mode: 'reconnect', connectionId: 'c1' }),
    );
    expect(wizard()).toBe('reconnect:c1');
  });

  const purpose = () =>
    container
      .querySelector('[data-testid="wizard"]')
      ?.getAttribute('data-purpose');

  it('tells the wizard it was opened for Knowledge', async () => {
    await act(async () => launchRef!(LINEAR, { purpose: 'knowledge' }));
    expect(purpose()).toBe('knowledge');
    await act(async () => launchRef!(DRIVE, { purpose: 'knowledge' }));
    expect(wizard()).toBe('connect:');
    expect(purpose()).toBe('knowledge');
  });

  it('leaves a plain connect without a purpose', async () => {
    await act(async () => launchRef!(DRIVE));
    expect(purpose()).toBe('');
  });
});
