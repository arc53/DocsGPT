import { useCallback, useRef, useState, type ReactNode } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';

import connectorsService from '../api/services/connectorsService';
import MCPServerModal from '../modals/MCPServerModal';
import type { ActiveState } from '../models/misc';
import { selectToken } from '../preferences/preferenceSlice';
import type { AppDispatch } from '../store';
import ConnectWizard, {
  type LaunchPurpose,
  type WizardMode,
} from './ConnectWizard';
import { loadConnectors } from './connectorsSlice';
import { isMcpPreset } from './launchRules';
import type { ConnectorDefinition } from './types';

export type LaunchOptions = {
  /** `connect` a new account, `reconnect` one, or `sync` more from one. */
  mode?: Exclude<WizardMode, 'done'>;
  connectionId?: string;
  /** An existing MCP tool to reconnect through the MCP server form. */
  mcpServer?: Record<string, unknown>;
  /**
   * Why the wizard opens. `knowledge` (Add knowledge, Knowledge's Connect a
   * service) starts with Sync into Knowledge on; otherwise it starts off.
   */
  purpose?: LaunchPurpose;
};

type Active =
  | {
      kind: 'wizard';
      connector: ConnectorDefinition;
      mode: WizardMode;
      connectionId?: string;
      mcpToolId?: string;
      purpose?: LaunchPurpose;
    }
  | {
      kind: 'mcp';
      connector: ConnectorDefinition;
      server?: Record<string, unknown>;
    }
  | null;

const isMcp = (connector: ConnectorDefinition) =>
  connector.auth_kind === 'mcp' || connector.auth_kind === 'mcp_oauth';

type LauncherCallbacks = {
  /** The run connected an account, or repaired one (a reconnect). */
  onConnected?: () => void;
  /** The run ended with nothing connected (cancelled, or closed early). */
  onCancel?: () => void;
};

/**
 * The one way to start connecting a catalog entry, used by every entry point
 * (the Connectors page and drawer, Add Source, Add Tool, the chat's Connect
 * card). Returns `launch` and the modals it drives; render `modals` once.
 *
 * Args:
 *   onConnected: Called when a run ends having connected or repaired an
 *     account.
 *   onCancel: Called when a run ends with nothing connected, so an opener
 *     that stepped aside (Add knowledge) can come back.
 */
export default function useConnectorLauncher({
  onConnected,
  onCancel,
}: LauncherCallbacks = {}) {
  const dispatch = useDispatch<AppDispatch>();
  const navigate = useNavigate();
  const token = useSelector(selectToken);
  const [active, setActive] = useState<Active>(null);
  // An MCP server saved in this run: its summary wizard closing is a connect.
  const mcpSaved = useRef(false);

  // Every close reads the connections again: a cancelled run may still have
  // signed in (the account exists, nothing was set up on it).
  const refresh = useCallback(() => {
    dispatch(loadConnectors({ token }));
  }, [dispatch, token]);

  /** End the run: tell the opener whether it connected anything. */
  const end = useCallback(
    (connected: boolean) => {
      setActive(null);
      refresh();
      const saved = mcpSaved.current;
      mcpSaved.current = false;
      if (connected || saved) onConnected?.();
      else onCancel?.();
    },
    [refresh, onConnected, onCancel],
  );

  const launch = useCallback(
    async (connector: ConnectorDefinition, options: LaunchOptions = {}) => {
      mcpSaved.current = false;
      if (isMcpPreset(connector)) {
        setActive({
          kind: 'wizard',
          connector,
          // Sync more from an account skips signing in, like any connector.
          mode: options.mode ?? 'connect',
          connectionId: options.connectionId,
          mcpToolId:
            typeof options.mcpServer?.id === 'string'
              ? options.mcpServer.id
              : undefined,
          purpose: options.purpose,
        });
        return;
      }
      if (isMcp(connector)) {
        setActive({
          kind: 'mcp',
          connector,
          server:
            options.mcpServer ??
            (connector.mcp_url
              ? {
                  displayName: connector.name,
                  server_url: connector.mcp_url,
                  auth_type:
                    connector.auth_kind === 'mcp_oauth' ? 'oauth' : 'none',
                  oauth_scopes: connector.oauth_scopes.join(', '),
                  preset: true,
                }
              : undefined),
        });
        return;
      }
      if (connector.key === 'custom_openapi') {
        // The API tool screen on the Tools page imports the spec; the tool
        // is only created when it is saved there.
        navigate('/settings/tools', { state: { newApiTool: true } });
        return;
      }
      setActive({
        kind: 'wizard',
        connector,
        mode: options.mode ?? 'connect',
        connectionId: options.connectionId,
        purpose: options.purpose,
      });
    },
    [navigate],
  );

  const afterMcpSave = async () => {
    if (active?.kind !== 'mcp') return;
    const connector = active.connector;
    mcpSaved.current = true;
    const list = await connectorsService.listConnections(token);
    refresh();
    const connections = (list?.connections ?? []) as {
      id: string;
      connector_key: string;
      updated_at: string | null;
    }[];
    // The newest connection for this connector is the one just saved.
    const saved = connections
      .filter((c) => c.connector_key === connector.key)
      .sort((a, b) =>
        (b.updated_at ?? '').localeCompare(a.updated_at ?? ''),
      )[0];
    if (saved) {
      setActive({
        kind: 'wizard',
        connector,
        mode: 'done',
        connectionId: saved.id,
      });
      return;
    }
    end(true);
  };

  const closeMcp = (state: ActiveState) => {
    if (state !== 'INACTIVE') return;
    // A save closes the form too; the summary follows (afterMcpSave).
    if (mcpSaved.current) setActive(null);
    else end(false);
  };

  const modals: ReactNode = (
    <>
      {active?.kind === 'wizard' && (
        <ConnectWizard
          connector={active.connector}
          mode={active.mode}
          connectionId={active.connectionId}
          mcpToolId={active.mcpToolId}
          purpose={active.purpose}
          // A wizard that does not say (an older run) connected nothing.
          onClose={(connected?: boolean) => end(connected === true)}
        />
      )}
      {active?.kind === 'mcp' && (
        <MCPServerModal
          modalState="ACTIVE"
          setModalState={closeMcp}
          server={active.server}
          onServerSaved={afterMcpSave}
        />
      )}
    </>
  );

  return { launch, modals };
}
