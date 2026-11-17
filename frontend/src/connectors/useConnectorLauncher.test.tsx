import { configureStore } from '@reduxjs/toolkit';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Provider } from 'react-redux';
import { MemoryRouter } from 'react-router-dom';

// The wizard is tested on its own; here only what it is opened with matters.
const wizardProps = vi.hoisted(() => ({
  onSynced: undefined as ((ids: string[]) => void) | undefined,
}));
vi.mock('./ConnectWizard', () => ({
  default: ({
    mode,
    connectionId,
    purpose,
    owner,
    onSynced,
    onClose,
  }: {
    mode: string;
    connectionId?: string;
    purpose?: string;
    owner?: string;
    onSynced?: (ids: string[]) => void;
    onClose: (connected?: boolean, toolIds?: string[]) => void;
  }) => {
    wizardProps.onSynced = onSynced;
    return (
      <div
        data-testid="wizard"
        data-purpose={purpose ?? ''}
        data-owner={owner ?? ''}
      >
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
        <button
          type="button"
          data-close="tools"
          onClick={() => onClose(true, ['tool-a', 'tool-b'])}
        />
        {/* A wizard from before the `connected` argument. */}
        <button type="button" data-close="bare" onClick={() => onClose()} />
      </div>
    );
  },
}));
// The MCP server form, as a stub that saves on demand.
type McpSavedStub = (
  toolId?: string,
  saved?: { connectionId: string | null },
) => void;
const mcpForm = vi.hoisted(() => ({
  onServerSaved: null as null | McpSavedStub,
}));
vi.mock('../modals/MCPServerModal', () => ({
  default: (props: { onServerSaved: McpSavedStub }) => {
    mcpForm.onServerSaved = props.onServerSaved;
    return <div data-testid="mcp-form" />;
  },
}));

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

const DRAWIO = {
  key: 'mcp:drawio',
  name: 'draw.io',
  auth_kind: 'mcp',
  mcp_url: 'https://mcp.draw.io/mcp',
  publisher: 'preset',
  sync_ingestor: null,
} as unknown as ConnectorDefinition;

const EXCALIDRAW = {
  ...DRAWIO,
  key: 'mcp:excalidraw',
  name: 'Excalidraw',
  mcp_url: 'https://mcp.excalidraw.com/mcp',
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
const onSynced = vi.fn();
const onNavigate = vi.fn();

function Harness() {
  const { launch, modals } = useConnectorLauncher({
    onConnected,
    onCancel,
    onSynced,
    onNavigate,
  });
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

  it.each([DRAWIO, EXCALIDRAW])(
    'opens the no-auth $name preset in the wizard',
    async (connector) => {
      await act(async () => launchRef!(connector));
      expect(wizard()).toBe('connect:');
    },
  );

  const purpose = () =>
    container
      .querySelector('[data-testid="wizard"]')
      ?.getAttribute('data-purpose');

  it("tells the wizard to connect for the team only when asked, so a team's chat still connects the person's own", async () => {
    const owner = () =>
      container
        .querySelector('[data-testid="wizard"]')
        ?.getAttribute('data-owner');
    await act(async () => launchRef!(DRIVE));
    expect(owner()).toBe('');
    await act(async () => launchRef!(DRIVE, { owner: 'team' }));
    expect(owner()).toBe('team');
    await act(async () =>
      launchRef!(LINEAR, {
        mode: 'reconnect',
        connectionId: 'c1',
        owner: 'team',
      }),
    );
    expect(owner()).toBe('team');
  });

  it('tells the wizard it was opened for Knowledge', async () => {
    await act(async () => launchRef!(LINEAR, { purpose: 'knowledge' }));
    expect(purpose()).toBe('knowledge');
    await act(async () => launchRef!(DRIVE, { purpose: 'knowledge' }));
    expect(wizard()).toBe('connect:');
    expect(purpose()).toBe('knowledge');
  });

  it('passes the sources a sync started on to its opener', async () => {
    await act(async () => launchRef!(DRIVE, { purpose: 'knowledge' }));
    wizardProps.onSynced!(['src-1']);
    expect(onSynced).toHaveBeenCalledWith(['src-1']);
  });

  it('leaves a plain connect without a purpose', async () => {
    await act(async () => launchRef!(DRIVE));
    expect(purpose()).toBe('');
  });

  const closeWith = async (how: 'connected' | 'cancel' | 'bare' | 'tools') =>
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

  it('hands its opener the tools the run set up', async () => {
    await act(async () => launchRef!(DRIVE));
    await closeWith('tools');
    expect(onConnected).toHaveBeenCalledWith(['tool-a', 'tool-b']);
  });

  it("hands its opener a saved MCP server's tool", async () => {
    const CUSTOM_MCP = {
      key: 'custom_mcp',
      name: 'MCP server',
      auth_kind: 'mcp',
      mcp_url: null,
      publisher: 'custom',
      sync_ingestor: null,
    } as unknown as ConnectorDefinition;
    await act(async () => launchRef!(CUSTOM_MCP));
    expect(container.querySelector('[data-testid="mcp-form"]')).not.toBeNull();
    // No connection to show a summary for: the run ends on the save.
    await act(async () => mcpForm.onServerSaved!('mcp-1'));
    expect(onConnected).toHaveBeenCalledWith(['mcp-1']);
  });

  it('opens the API tool editor through its opener', async () => {
    const OPENAPI = {
      key: 'custom_openapi',
      name: 'OpenAPI',
      auth_kind: 'none',
      mcp_url: null,
      publisher: 'custom',
      sync_ingestor: null,
    } as unknown as ConnectorDefinition;
    await act(async () => launchRef!(OPENAPI));
    expect(onNavigate).toHaveBeenCalledWith('/settings/tools', {
      state: { newApiTool: true },
    });
  });

  it('hands its opener no tool after an MCP server signs in again', async () => {
    const CUSTOM_MCP = {
      key: 'custom_mcp',
      name: 'MCP server',
      auth_kind: 'mcp',
      mcp_url: null,
      publisher: 'custom',
      sync_ingestor: null,
    } as unknown as ConnectorDefinition;
    await act(async () =>
      launchRef!(CUSTOM_MCP, {
        mode: 'reconnect',
        mcpServer: { id: 'mcp-old' },
      }),
    );
    await act(async () => mcpForm.onServerSaved!('mcp-old'));
    expect(onConnected).toHaveBeenCalledWith([]);
  });
  it("ends a team's MCP save on the connection it names, never on the caller's own", async () => {
    const CUSTOM_MCP = {
      key: 'custom_mcp',
      name: 'MCP server',
      auth_kind: 'mcp',
      mcp_url: null,
      publisher: 'custom',
      sync_ingestor: null,
    } as unknown as ConnectorDefinition;
    // The caller's own newest sign-in to a custom server.
    vi.mocked(connectorsService.listConnections).mockResolvedValue({
      success: true,
      connections: [
        { id: 'mine', connector_key: 'custom_mcp', updated_at: '2026-11-17' },
      ],
    });
    await act(async () => launchRef!(CUSTOM_MCP));
    vi.mocked(connectorsService.listConnections).mockClear();
    await act(async () =>
      mcpForm.onServerSaved!('mcp-team', { connectionId: 'conn-team' }),
    );
    expect(wizard()).toBe('done:conn-team');
    // The summary names the new account: the lists are read again for it.
    expect(connectorsService.listConnections).toHaveBeenCalled();

    // A tool on each person's own sign-in has no connection: the run ends.
    await act(async () => launchRef!(CUSTOM_MCP));
    await act(async () =>
      mcpForm.onServerSaved!('mcp-each', { connectionId: null }),
    );
    expect(wizard()).toBeUndefined();
    expect(onConnected).toHaveBeenCalledWith(['mcp-each']);
  });
});
