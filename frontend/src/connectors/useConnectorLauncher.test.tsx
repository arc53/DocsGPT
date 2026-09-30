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
    onClose,
  }: {
    mode: string;
    connectionId?: string;
    purpose?: string;
    onClose: (connected?: boolean) => void;
  }) => (
    <div data-testid="wizard" data-purpose={purpose ?? ''}>
      <span data-testid="wizard-state">{`${mode}:${connectionId ?? ''}`}</span>
      <button
        type="button"
        data-close="connected"
        onClick={() => onClose(true)}
      />
      <button
        type="button"
        data-close="cancel"
        onClick={() => onClose(false)}
      />
      {/* A wizard from before the `connected` argument. */}
      <button type="button" data-close="bare" onClick={() => onClose()} />
    </div>
  ),
}));
vi.mock('../modals/MCPServerModal', () => ({ default: () => null }));

import connectorsService from '../api/services/connectorsService';
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

const onConnected = vi.fn();
const onCancel = vi.fn();

function Harness() {
  const { launch, modals } = useConnectorLauncher({ onConnected, onCancel });
  launchRef = launch;
  return <>{modals}</>;
}

describe('useConnectorLauncher', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(async () => {
    onConnected.mockReset();
    onCancel.mockReset();
    vi.spyOn(connectorsService, 'getCatalog').mockResolvedValue({
      success: true,
      connectors: [],
    });
    vi.spyOn(connectorsService, 'listConnections').mockResolvedValue({
      success: true,
      connections: [],
    });
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
    vi.restoreAllMocks();
  });

  const wizard = () =>
    container.querySelector('[data-testid="wizard-state"]')?.textContent;

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

  const closeWith = async (how: 'connected' | 'cancel' | 'bare') =>
    act(async () =>
      container
        .querySelector<HTMLButtonElement>(`[data-close="${how}"]`)!
        .click(),
    );

  it('reports a connect when the wizard closes having connected', async () => {
    await act(async () => launchRef!(DRIVE, { purpose: 'knowledge' }));
    await closeWith('connected');
    expect(wizard()).toBeUndefined();
    expect(onConnected).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    // The connections list is read again either way.
    expect(connectorsService.listConnections).toHaveBeenCalled();
  });

  it('reports a cancel, not a connect, when nothing was connected', async () => {
    await act(async () => launchRef!(DRIVE, { purpose: 'knowledge' }));
    await closeWith('cancel');
    expect(wizard()).toBeUndefined();
    expect(onConnected).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(connectorsService.listConnections).toHaveBeenCalled();
  });

  it('treats a close without the argument as a cancel', async () => {
    await act(async () => launchRef!(DRIVE));
    await closeWith('bare');
    expect(onConnected).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
